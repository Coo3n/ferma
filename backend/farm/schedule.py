"""Смены: запуск сценария по расписанию, каждому телефону — своё время.

Смена — «что, на ком, по каким дням и в какое окно». План дня строится
заново из seed = id+дата+serial, поэтому он одинаков после перезапуска
фермы и не хранится. Хранится только то, что уже случилось с каждым
моментом плана (запущен / пропущен), — чтобы перезапуск не повторил запуск.

Антибан: телефоны не стартуют одновременно. Каждый получает свои случайные
моменты внутри окна, не ближе MIN_GAP друг к другу; запуски, которые ферма
проспала (была выключена), не выстреливают пачкой, а растягиваются на
CATCHUP_SPREAD.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import uuid
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger("farm.schedule")

SCHEDULES_FILE = config.DATA_DIR / "schedules.json"

TICK_S = 30
MIN_GAP_S = 20 * 60          # моменты одного телефона не ближе 20 мин
RETRY_S = 5 * 60             # офлайн/занят — повтор через 5 мин
LATE_S = 2 * TICK_S          # опоздание больше этого — догоняем вразброс
CATCHUP_SPREAD_S = 5 * 60
MAX_RUNS = 10
TARGET_KINDS = ("all", "group", "tag", "serials")

WAIT, STARTED, SKIPPED = "wait", "started", "skipped"


# ------------------------------------------------------------- проверка

def _hm(value: str) -> int:
    """«10:30» → минуты от полуночи."""
    try:
        h, m = str(value).strip().split(":")
        h, m = int(h), int(m)
    except Exception:  # noqa: BLE001
        raise ValueError(f"время «{value}» — нужно вида 10:30") from None
    if not (0 <= h <= 24 and 0 <= m < 60) or h * 60 + m > 24 * 60:
        raise ValueError(f"время «{value}» вне суток")
    return h * 60 + m


def normalize(data: dict, old: dict | None = None) -> dict:
    """Проверить и привести смену к одному виду. ValueError — понятным текстом."""
    old = old or {}
    src = {**old, **(data or {})}
    name = str(src.get("name") or "").strip()
    if not name:
        raise ValueError("назовите смену")
    scenario = str(src.get("scenario") or "").strip()
    if not scenario:
        raise ValueError("выберите сценарий")
    target = src.get("target") or {"kind": "all", "value": None}
    kind = target.get("kind") or "all"
    if kind not in TARGET_KINDS:
        raise ValueError("на ком запускать: все, группа, тег или выбранные телефоны")
    value = target.get("value")
    if kind in ("group", "tag"):
        value = str(value or "").strip()
        if not value:
            raise ValueError("выберите группу" if kind == "group" else "выберите тег")
    elif kind == "serials":
        value = [str(s) for s in (value or []) if str(s).strip()]
        if not value:
            raise ValueError("выберите хотя бы один телефон")
    else:
        value = None
    days = sorted({int(d) for d in (src.get("days") if src.get("days") is not None else range(7))})
    if not days or any(d < 0 or d > 6 for d in days):
        raise ValueError("выберите дни недели")
    window = src.get("window") or {}
    wf, wt = window.get("from", "10:00"), window.get("to", "14:00")
    if _hm(wf) >= _hm(wt):
        raise ValueError("окно: «с» должно быть раньше «до» (через полночь нельзя)")
    runs = int(src.get("runs_per_day") or 1)
    if not 1 <= runs <= MAX_RUNS:
        raise ValueError(f"запусков в день: от 1 до {MAX_RUNS}")
    params = src.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("параметры сценария — неверный вид")
    return {
        "id": old.get("id") or src.get("id") or uuid.uuid4().hex[:8],
        "name": name[:80],
        "scenario": scenario,
        "params": params,
        "target": {"kind": kind, "value": value},
        "days": days,
        "window": {"from": wf, "to": wt},
        "runs_per_day": runs,
        "enabled": bool(src.get("enabled", True)),
    }


# ------------------------------------------------------------------ план

def _window_dt(sched: dict, day: Date) -> tuple[datetime, datetime]:
    base = datetime(day.year, day.month, day.day)
    return (base + timedelta(minutes=_hm(sched["window"]["from"])),
            base + timedelta(minutes=_hm(sched["window"]["to"])))


def plan_times(sched: dict, day: Date, serial: str) -> list[datetime]:
    """Моменты запуска телефона на день. Пусто — день не рабочий.

    Детерминировано: тот же id+дата+serial дают те же моменты. Равномерно
    среди всех раскладок с шагом ≥ MIN_GAP: n точек в «свободном» отрезке
    (окно минус обязательные зазоры), затем к i-й прибавляется i зазоров.
    Узкое окно урезает число запусков, а не нарушает зазор.
    """
    if day.weekday() not in sched["days"]:
        return []
    start, end = _window_dt(sched, day)
    span = int((end - start).total_seconds())
    n = max(1, min(int(sched["runs_per_day"]), (span - 1) // MIN_GAP_S + 1))
    free = span - 1 - MIN_GAP_S * (n - 1)
    rng = random.Random(f"{sched['id']}|{day.isoformat()}|{serial}")
    points = sorted(rng.randint(0, free) for _ in range(n))
    return [start + timedelta(seconds=p + MIN_GAP_S * i) for i, p in enumerate(points)]


def _tags(dev) -> list:
    return list(getattr(dev, "tags", None) or [])


def target_serials(sched: dict, devices: list) -> list[str]:
    """Кто входит в смену. Выбранные телефоны — даже если сейчас не видны:
    в плане они честно покажутся пропущенными."""
    kind, value = sched["target"]["kind"], sched["target"]["value"]
    if kind == "serials":
        return list(value)
    if kind == "group":
        return [d.serial for d in devices if (getattr(d, "group", "") or "") == value]
    if kind == "tag":
        return [d.serial for d in devices if value in _tags(d)]
    return [d.serial for d in devices]


# ------------------------------------------------------------ планировщик

class Scheduler:
    def __init__(self, path: Path | str = SCHEDULES_FILE, *, runner=None, registry=None,
                 clock: Callable[[], datetime] = datetime.now) -> None:
        self.path = Path(path)
        self._runner = runner
        self._registry = registry
        self.clock = clock
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        data = self._load()
        self._items: list[dict] = data.get("schedules", [])
        # «id|дата» → serial → epoch-момент (строкой) → {status, note, job, retry}
        self._state: dict[str, dict] = data.get("state", {})
        self._since: dict[str, float] = data.get("since", {})

    # ---- зависимости подтягиваем лениво: тесты подсовывают свои
    @property
    def runner(self):
        if self._runner is None:
            from .devices.runner import runner
            self._runner = runner
        return self._runner

    @property
    def registry(self):
        if self._registry is None:
            from .devices import registry
            self._registry = registry
        return self._registry

    # ---- хранение
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    def _save(self) -> None:
        today = self.clock().date()
        keep = {(today - timedelta(days=1)).isoformat(), today.isoformat()}
        self._state = {k: v for k, v in self._state.items() if k.rsplit("|", 1)[-1] in keep}
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"schedules": self._items, "state": self._state,
                                       "since": self._since}, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)
        except Exception as e:  # noqa: BLE001
            log.warning("не удалось сохранить смены: %s", e)

    # ---- CRUD
    def all(self) -> list[dict]:
        with self._lock:
            return [dict(s) for s in self._items]

    def get(self, sid: str) -> dict | None:
        with self._lock:
            return next((dict(s) for s in self._items if s["id"] == sid), None)

    def create(self, data: dict) -> dict:
        with self._lock:
            sched = normalize({k: v for k, v in (data or {}).items() if k != "id"})
            self._items.append(sched)
            self._since[sched["id"]] = self.clock().timestamp()
            self._save()
            return dict(sched)

    def update(self, sid: str, data: dict) -> dict:
        with self._lock:
            for i, s in enumerate(self._items):
                if s["id"] == sid:
                    new = normalize({k: v for k, v in (data or {}).items() if k != "id"}, s)
                    self._items[i] = new
                    # Новое окно/число запусков — новый план; прошедшие
                    # моменты не должны выстрелить все разом.
                    self._since[sid] = self.clock().timestamp()
                    self._save()
                    return dict(new)
        raise KeyError(sid)

    def delete(self, sid: str) -> None:
        with self._lock:
            before = len(self._items)
            self._items = [s for s in self._items if s["id"] != sid]
            if len(self._items) == before:
                raise KeyError(sid)
            self._since.pop(sid, None)
            self._state = {k: v for k, v in self._state.items() if not k.startswith(sid + "|")}
            self._save()

    def toggle(self, sid: str, enabled: bool | None = None) -> dict:
        with self._lock:
            for s in self._items:
                if s["id"] == sid:
                    s["enabled"] = (not s["enabled"]) if enabled is None else bool(enabled)
                    if s["enabled"]:
                        self._since[sid] = self.clock().timestamp()
                    self._save()
                    return dict(s)
        raise KeyError(sid)

    def pause_all(self) -> int:
        """Аварийная остановка: выключить все включённые смены. Иначе после
        «Остановить всё» смена через 20 минут запускала ферму снова."""
        with self._lock:
            n = 0
            for s in self._items:
                if s["enabled"]:
                    s["enabled"] = False
                    n += 1
            if n:
                self._save()
            return n

    # ---- план со статусами
    def _slot(self, sid: str, day: Date, serial: str, at: datetime) -> dict:
        key = f"{sid}|{day.isoformat()}"
        bucket = self._state.setdefault(key, {}).setdefault(serial, {})
        return bucket.setdefault(str(int(at.timestamp())), {"status": WAIT})

    def _peek(self, sid: str, day: Date, serial: str, at: datetime) -> dict:
        return (self._state.get(f"{sid}|{day.isoformat()}", {}).get(serial, {})
                .get(str(int(at.timestamp())), {"status": WAIT}))

    def plan(self, sid: str, day: Date | None = None) -> dict:
        with self._lock:
            sched = next((s for s in self._items if s["id"] == sid), None)
            if sched is None:
                raise KeyError(sid)
            day = day or self.clock().date()
            devices = self.registry.all()
            by_serial = {d.serial: d for d in devices}
            start, end = _window_dt(sched, day)
            phones = []
            for serial in target_serials(sched, devices):
                dev = by_serial.get(serial)
                slots = []
                for at in plan_times(sched, day, serial):
                    st = self._peek(sid, day, serial, at)
                    slots.append({"at": at.timestamp(), "status": st["status"],
                                  "note": st.get("note", ""), "job": st.get("job"),
                                  "retry": st.get("retry")})
                phones.append({"serial": serial, "name": dev.name if dev else serial,
                               "online": bool(dev and dev.online), "slots": slots})
            return {"id": sid, "date": day.isoformat(), "working": day.weekday() in sched["days"],
                    "window": {"from": start.timestamp(), "to": end.timestamp()},
                    "phones": phones}

    def next_run(self, sched: dict, now: datetime | None = None) -> float | None:
        """Ближайший момент, когда смена кого-то запустит."""
        now = now or self.clock()
        if not sched["enabled"]:
            return None
        serials = target_serials(sched, self.registry.all())
        if not serials:
            return None
        best = None
        today = now.date()
        since = self._since.get(sched["id"], 0)
        _, end = _window_dt(sched, today)
        for serial in serials:
            for at in plan_times(sched, today, serial):
                st = self._peek(sched["id"], today, serial, at)
                if st["status"] != WAIT or at.timestamp() < since or now >= end:
                    continue
                t = max(at.timestamp(), st.get("retry") or 0, now.timestamp())
                best = t if best is None else min(best, t)
        if best is not None:
            return best
        for k in range(1, 8):
            day = today + timedelta(days=k)
            times = [at.timestamp() for s in serials for at in plan_times(sched, day, s)]
            if times:
                return min(times)
        return None

    # ---- тик
    def tick(self) -> int:
        """Один проход: запустить, что пора. Возвращает число запусков."""
        now = self.clock()
        ts = now.timestamp()
        started = 0
        with self._lock:
            changed = False
            devices = self.registry.all()
            for sched in self._items:
                if not sched["enabled"]:
                    continue
                day = now.date()
                start, end = _window_dt(sched, day)
                if now < start:
                    continue
                since = self._since.get(sched["id"], 0)
                batch = f"sch-{sched['id']}-{day.isoformat()}"
                for serial in target_serials(sched, devices):
                    submitted = False
                    for at in plan_times(sched, day, serial):
                        if at > now:
                            break
                        st = self._slot(sched["id"], day, serial, at)
                        if st["status"] != WAIT:
                            continue
                        if at.timestamp() < since:
                            st.update(status=SKIPPED, note="смену создали или изменили позже")
                            changed = True
                            continue
                        if now >= end:
                            st.update(status=SKIPPED, note=st.get("note") or "окно закончилось")
                            changed = True
                            continue
                        if st.get("retry") and ts < st["retry"]:
                            continue
                        # Ферма проспала момент — не стреляем всем разом.
                        if not st.get("retry") and ts - at.timestamp() > LATE_S:
                            rng = random.Random(f"{sched['id']}|{at.timestamp()}|{serial}|late")
                            st["retry"] = ts + rng.randint(0, CATCHUP_SPREAD_S)
                            changed = True
                            continue
                        if submitted:
                            continue
                        dev = self.registry.get(serial)
                        reason = ("телефон не подключён" if dev is None or not dev.online
                                  else "телефон выключен из работы" if not getattr(dev, "enabled", True)
                                  else "телефон занят" if dev.busy_job else "")
                        if reason:
                            st.update(note=reason, retry=ts + RETRY_S)
                            changed = True
                            continue
                        try:
                            jobs = self.runner.submit(sched["scenario"], [serial],
                                                      params=dict(sched.get("params") or {}),
                                                      batch=batch)
                        except Exception as e:  # noqa: BLE001
                            st.update(status=SKIPPED, note=f"не запустился: {e}")
                            changed = True
                            continue
                        st.update(status=STARTED, note="", job=jobs[0].id if jobs else None)
                        st.pop("retry", None)
                        submitted = True
                        started += 1
                        changed = True
            if changed:
                self._save()
        return started

    # ---- поток
    def _loop(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                n = self.tick()
                if n:
                    log.info("смены: запущено %d", n)
            except Exception:  # noqa: BLE001
                log.exception("смены: ошибка тика")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="schedule", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None


scheduler = Scheduler()
