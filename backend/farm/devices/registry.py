"""Реестр устройств: обнаружение, здоровье, занятость, авто-восстановление."""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .. import adb, config, streaming
from . import pool, power
from .network import net

log = logging.getLogger("farm.devices")

LABELS_FILE = config.DATA_DIR / "devices.json"
GROUPS_FILE = config.DATA_DIR / "groups.json"
TAGS_FILE = config.DATA_DIR / "tags.json"
MAX_TAGS = 10
MAX_TAG_LEN = 24


def clean_tags(tags) -> list[str]:
    """Без пробелов по краям, без повторов (без учёта регистра), ≤10 штук по ≤24 символа."""
    out: list[str] = []
    seen: set[str] = set()
    for t in tags or []:
        t = " ".join(str(t).split())[:MAX_TAG_LEN].strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:MAX_TAGS]


@dataclass
class Device:
    serial: str
    state: str = "offline"  # device | offline | unauthorized | unknown
    label: str = ""
    group: str = ""  # одна группа на телефон: «VK-10», «Тест» — фильтр и массовые действия
    tags: list[str] = field(default_factory=list)  # сколько угодно меток: «прогрет», «новый»
    model: str = ""
    brand: str = ""
    android: str = ""
    sdk: str = ""
    width: int = 0
    height: int = 0
    battery: int | None = None
    temperature: float | None = None
    charging: str = ""
    busy_job: str | None = None
    enabled: bool = True  # можно вывести устройство из ротации вручную
    last_seen: float = 0.0
    first_seen: float = field(default_factory=time.time)
    error: str = ""
    rest: str = ""  # причина «отдыха» (разряд/перегрев); пусто — телефон в строю, см. power.py

    @property
    def online(self) -> bool:
        return self.state == "device"

    @property
    def available(self) -> bool:
        return self.online and self.enabled and not self.rest and self.busy_job is None

    @property
    def name(self) -> str:
        return self.label or self.model or self.serial

    @property
    def network(self) -> bool:
        """Подключено по TCP, а не проводом."""
        return adb.is_network_serial(self.serial)

    def forget_health(self) -> None:
        """Забыть метрики живого устройства: у отключённого их знать неоткуда."""
        self.battery = None
        self.temperature = None
        self.charging = ""

    def warnings(self) -> list[str]:
        w = []
        if self.online:
            if self.temperature is not None and self.temperature >= config.TEMP_ALERT_C:
                w.append(f"перегрев {self.temperature:.0f}°C")
            if self.battery is not None:
                if self.battery <= config.BATTERY_LOW:
                    w.append(f"заряд {self.battery}%")
                elif self.battery >= config.BATTERY_HIGH and self.charging:
                    w.append(f"держит {self.battery}% на зарядке")
        if self.rest:
            w.append(self.rest)
        if self.state == "unauthorized":
            # У платы без монитора подтвердить ключ пальцем негде — только
            # прописать публичный ключ хоста в образ.
            w.append("нет доступа — на плате не прописан ключ этого компьютера (adbkey.pub, см. README)"
                     if self.network else
                     "нет доступа — нажмите «Разрешить» в окне отладки на телефоне")
        if self.error:
            w.append(self.error)
        return w

    def to_dict(self) -> dict:
        d = asdict(self)
        d["online"] = self.online
        d["available"] = self.available
        d["name"] = self.name
        d["warnings"] = self.warnings()
        d["u2"] = pool.is_connected(self.serial)
        d["network"] = self.network
        d["transport"] = "tcp" if self.network else "usb"
        d["power"] = power.guard.view(self.serial)
        from .. import accounts   # registry грузится раньше accounts — импорт по месту
        d["accounts"] = accounts.summary_for(self.serial)
        # {"on", "locked"} или None — ещё не проверяли (кадров не просили).
        d["screen"] = streaming.screen_info(self.serial) if self.online else None
        if not self.online:
            # Показывать заряд отключённого телефона нечестно: цифра старая,
            # а выглядит как текущая. Чистим на выдаче, а не только в момент
            # отключения — иначе метрики переживут перезапуск сервера.
            d["battery"] = None
            d["temperature"] = None
            d["charging"] = ""
        return d


class Registry:
    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_health: dict[str, float] = {}
        self._labels: dict[str, str] = self._load_labels()
        self._groups: dict[str, str] = self._load_json(GROUPS_FILE)
        self._tags: dict[str, list[str]] = self._load_json(TAGS_FILE)
        self.adb_version = ""

    # ---------- метки ----------
    def _load_labels(self) -> dict[str, str]:
        try:
            return json.loads(Path(LABELS_FILE).read_text("utf-8"))
        except Exception:
            return {}

    def _save_labels(self) -> None:
        try:
            Path(LABELS_FILE).write_text(json.dumps(self._labels, ensure_ascii=False, indent=2), "utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("не удалось сохранить метки: %s", e)

    def set_label(self, serial: str, label: str) -> None:
        with self._lock:
            self._labels[serial] = label
            self._save_labels()
            if serial in self._devices:
                self._devices[serial].label = label

    @staticmethod
    def _load_json(path) -> dict:
        try:
            return json.loads(Path(path).read_text("utf-8"))
        except Exception:
            return {}

    def set_group(self, serial: str, group: str) -> None:
        group = (group or "").strip()
        with self._lock:
            if group:
                self._groups[serial] = group
            else:
                self._groups.pop(serial, None)
            try:
                Path(GROUPS_FILE).write_text(json.dumps(self._groups, ensure_ascii=False, indent=2), "utf-8")
            except Exception as e:  # noqa: BLE001
                log.warning("не удалось сохранить группы: %s", e)
            if serial in self._devices:
                self._devices[serial].group = group

    def groups(self) -> list[str]:
        with self._lock:
            return sorted(set(self._groups.values()), key=str.lower)

    # ---------- теги ----------
    def tags_of(self, serial: str) -> list[str]:
        with self._lock:
            return list(self._tags.get(serial, []))

    def set_tags(self, serial: str, tags) -> list[str]:
        tags = clean_tags(tags)
        with self._lock:
            if tags:
                self._tags[serial] = tags
            else:
                self._tags.pop(serial, None)
            try:
                Path(TAGS_FILE).write_text(json.dumps(self._tags, ensure_ascii=False, indent=2), "utf-8")
            except Exception as e:  # noqa: BLE001
                log.warning("не удалось сохранить теги: %s", e)
            if serial in self._devices:
                self._devices[serial].tags = list(tags)
        return tags

    def add_tags(self, serial: str, tags) -> list[str]:
        return self.set_tags(serial, self.tags_of(serial) + list(tags or []))

    def remove_tags(self, serial: str, tags) -> list[str]:
        drop = {t.lower() for t in clean_tags(tags)}
        return self.set_tags(serial, [t for t in self.tags_of(serial) if t.lower() not in drop])

    def all_tags(self) -> list[str]:
        with self._lock:
            return sorted({t for ts in self._tags.values() for t in ts}, key=str.lower)

    # ---------- доступ ----------
    def all(self) -> list[Device]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda d: (not d.online, d.name.lower()))

    def get(self, serial: str) -> Device | None:
        with self._lock:
            return self._devices.get(serial)

    def online_serials(self) -> list[str]:
        return [d.serial for d in self.all() if d.online and d.enabled]

    def set_enabled(self, serial: str, enabled: bool) -> None:
        with self._lock:
            if serial in self._devices:
                self._devices[serial].enabled = enabled

    def forget(self, serial: str) -> bool:
        """Убрать устройство из реестра совсем.

        Для сетевого адреса, снятого со стойки: иначе плитка так и висит
        offline до перезапуска сервера.
        """
        with self._lock:
            d = self._devices.pop(serial, None)
        if d is None:
            return False
        self._last_health.pop(serial, None)
        pool.drop(serial)
        return True

    # ---------- занятость ----------
    def acquire(self, serial: str, job_id: str) -> bool:
        with self._lock:
            d = self._devices.get(serial)
            if d is None or not d.online or d.busy_job is not None:
                return False
            d.busy_job = job_id
            return True

    def release(self, serial: str, job_id: str | None = None) -> None:
        with self._lock:
            d = self._devices.get(serial)
            if d and (job_id is None or d.busy_job == job_id):
                d.busy_job = None

    # ---------- опрос ----------
    def refresh_once(self) -> None:
        found = adb.list_devices()
        now = time.time()
        seen: set[str] = set()

        with self._lock:
            for a in found:
                seen.add(a.serial)
                d = self._devices.get(a.serial)
                if d is None:
                    d = Device(serial=a.serial, label=self._labels.get(a.serial, ""),
                               group=self._groups.get(a.serial, ""),
                               tags=list(self._tags.get(a.serial, [])))
                    self._devices[a.serial] = d
                    log.info("новое устройство: %s (%s)", a.serial, a.state)
                was_online = d.online
                d.state = a.state
                d.last_seen = now
                if a.props.get("model"):
                    d.model = a.props["model"].replace("_", " ")
                if not was_online and d.online:
                    d.error = ""
                    self._last_health.pop(a.serial, None)
                elif was_online and not d.online:
                    d.forget_health()

            # Известные платы показываем в ферме всегда, даже если adb их
            # никогда не видел: 20 плиток, из которых часть красная, полезнее
            # пустого списка — сразу ясно, кого чинить.
            for target in net.all():
                if target.address not in self._devices:
                    self._devices[target.address] = Device(
                        serial=target.address,
                        label=self._labels.get(target.address, "") or target.label,
                        group=self._groups.get(target.address, ""),
                        tags=list(self._tags.get(target.address, [])),
                    )

            for serial, d in self._devices.items():
                if serial not in seen and d.state != "offline":
                    log.warning("устройство пропало: %s", serial)
                    d.state = "offline"
                    # busy_job не трогаем: задача ещё идёт (или падает) и
                    # сама освободит телефон в finally runner'а. Сброс здесь
                    # делал вернувшийся телефон «свободным» посреди задачи.
                    d.forget_health()
                    pool.drop(serial)

        # медленные запросы — вне блокировки
        for d in list(self._devices.values()):
            if not d.online:
                continue
            # Телефон на экране у человека: dumpsys делит канал adb с касаниями
            # и добавляет лаг. Пока его смотрят, опрашиваем в 6 раз реже.
            every = config.HEALTH_INTERVAL * (6 if streaming.is_live(d.serial) else 1)
            if now - self._last_health.get(d.serial, 0) < every:
                continue
            self._last_health[d.serial] = now
            self._read_health(d)
            self._apply_power(d)

    def _read_health(self, d: Device) -> None:
        try:
            if not d.android:
                d.android = adb.getprop(d.serial, "ro.build.version.release")
                d.sdk = adb.getprop(d.serial, "ro.build.version.sdk")
                d.brand = adb.getprop(d.serial, "ro.product.brand")
                if not d.model:
                    d.model = adb.getprop(d.serial, "ro.product.model")
            if not d.width:
                size = adb.screen_size(d.serial)
                if size:
                    d.width, d.height = size
            b = adb.battery(d.serial)
            d.battery = b.get("level", d.battery)
            d.temperature = b.get("temperature", d.temperature)
            d.charging = b.get("plugged", "")
            d.error = ""
        except Exception as e:  # noqa: BLE001
            d.error = str(e)[:200]

    def _apply_power(self, d: Device) -> None:
        """Заряд/температура → стейт-машина power.py; при уходе на отдых снимает запуски."""
        if d.battery is None:
            return
        res = power.guard.update(d.serial, d.battery, d.temperature, bool(d.charging))
        d.rest = res["rest_reason"]
        if res["entered_rest"]:
            from .runner import runner   # runner импортирует registry — по месту
            try:
                runner.stop_for_power(d.serial, d.rest)
            except Exception as e:  # noqa: BLE001
                log.warning("не удалось снять запуски с %s: %s", d.serial, e)

    def recover(self, serial: str) -> str:
        """Попытка вернуть отвалившееся устройство в строй."""
        if adb.is_network_serial(serial):
            return self._recover_network(serial)
        msgs = [adb.reconnect_offline().strip()]
        pool.drop(serial)
        time.sleep(1.0)
        self.refresh_once()
        d = self.get(serial)
        if d and d.online:
            msgs.append("устройство в сети")
        else:
            # Перезапуск adb-сервера здесь рвал связь со всей фермой ради
            # одного телефона. Общее переподключение — отдельная кнопка в
            # шапке, с подтверждением.
            msgs.append("телефон всё ещё не в сети — проверьте кабель или Wi-Fi; "
                        "крайняя мера — «Переподключить телефоны» в шапке (затронет всю ферму)")
        return " | ".join(m for m in msgs if m)

    def _recover_network(self, serial: str) -> str:
        """Сетевую плату чинит не `reconnect`, а переподключение по адресу.

        Перезапускать ради неё adb-сервер нельзя: это уронит все остальные
        устройства фермы.
        """
        pool.drop(serial)
        if net.get(serial) is None:
            net.add(serial)  # подключались вручную мимо списка — запомним
        ok, message = net.connect_now(serial)
        msgs = [message.strip()]
        if ok:
            time.sleep(1.0)
            self.refresh_once()
            d = self.get(serial)
            msgs.append("устройство в сети" if d and d.online else "adb принял адрес, устройство ещё не поднялось")
        return " | ".join(m for m in msgs if m)

    # ---------- фон ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        adb.start_server()
        self.adb_version = adb.version()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="device-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.refresh_once()
            except Exception as e:  # noqa: BLE001
                log.exception("сбой опроса: %s", e)
            self._stop.wait(config.POLL_INTERVAL)


registry = Registry()
