"""Очередь задач и исполнители.

На каждое устройство — своя FIFO-очередь и свой поток. Устройства работают
параллельно, внутри одного устройства сценарии идут по очереди (иначе они
дерутся за экран). Это даёт корректный параллелизм до 20+ устройств без
дополнительной настройки.
"""
from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import config, control, deviations as dv, obstacle, scenarios, stepflow
from ..explain import explain
from ..context import (Cancelled, Finished, DeviceContext, HOLD_DECISIONS, HOLD_DROP, HOLD_GO, HOLD_SKIP,
                       HOLD_RETRY, HOLD_WORDS, StepFailed, normalize_target)
from ..recorder import codegen as recorder_codegen, save as recorder_save, steps as recorder_steps
from .registry import registry

log = logging.getLogger("farm.runner")

QUEUED, RUNNING, PASSED, FAILED, CANCELLED = "queued", "running", "passed", "failed", "cancelled"
# Задача стоит на промахнувшемся шаге и ждёт решения человека, НЕ отпуская
# устройство: смысл остановки в том, что экран на телефоне ещё тот самый.
# Поэтому HELD — это разновидность RUNNING, а не завершённое состояние: задачу
# в нём можно отменить, но нельзя удалить из журнала.
HELD = "held"
# Отмена работающей задачи кооперативная: поток прерывается на ближайшей
# проверке отмены, а не в момент нажатия. Без отдельного статуса задача до
# этого мгновения выглядит как обычная работающая — и человек жмёт «отменить»
# второй раз, думая, что не сработало. CANCELLING и есть это «уже отменяю».
CANCELLING = "cancelling"
ACTIVE = (QUEUED, RUNNING, HELD, CANCELLING)
DONE = (PASSED, FAILED, CANCELLED)


@dataclass
class Job:
    id: str
    scenario_key: str
    scenario_name: str
    serial: str
    device_name: str
    params: dict
    status: str = QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str = ""
    lines: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    # Остановка на человеке: чем задача встала, когда, и что человек ответил.
    held_reason: str = ""
    held_kind: str = ""     # "blind" — вопрос про шаг вслепую, "lost" — экран не тот
    held_obstacle: str = ""  # слепок экрана для «показать, как быть» (lost)
    held_at: float | None = None
    decision: str = ""
    # Исправленная цель к решению «повторить»; click_target забирает её раз.
    target_patch: dict | None = None
    # Отладка: с какого шага начать (с нуля) и во сколько раз замедлить.
    # Один id на одно нажатие «Запустить»: «Запуски» показывают ход именно
    # этого запуска («12 из 40 готово»), а не всей истории.
    batch: str = ""
    start_step: int = 0
    stop_step: int | None = None  # не включая; start+1 — прогон одного шага
    speed: float = 1.0
    # Ход по шагам записанного сценария: текущий, всего и хронология
    # [{i, label, status, secs}] — из неё же собирается отчёт.
    step_index: int = -1
    step_total: int = 0
    step_label: str = ""
    timeline: list = field(default_factory=list)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _decided: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at

    def add_line(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.lines.append(f"{stamp}  {text}")
        if len(self.lines) > 2000:
            del self.lines[:500]

    def to_dict(self, with_log: bool = False) -> dict:
        d = {
            "id": self.id,
            "scenario_key": self.scenario_key,
            "scenario_name": self.scenario_name,
            "serial": self.serial,
            "device_name": self.device_name,
            "params": self.params,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": round(self.duration, 1),
            "error": self.error,
            "artifacts": [Path(a).name for a in self.artifacts],
            # PASSED — не то же самое, что «нашлось чисто»: резолвер мог
            # доехать запасным слоем (шаблон/координаты) с пониженным запасом
            # прочности. Без этого поля узнать об этом можно было только
            # сверив id задачи со списком «Отклонения» вручную.
            "degraded": dv.deviations.job_has_kind(self.id, dv.LAYER),
            "log_size": len(self.lines),
            "held_reason": self.held_reason,
            "held_kind": self.held_kind,
            "held_obstacle": self.held_obstacle,
            "held_at": self.held_at,
            "decision": self.decision,
            "batch": self.batch,
            "start_step": self.start_step,
            "stop_step": self.stop_step,
            "speed": self.speed,
            "step_index": self.step_index,
            "step_total": self.step_total,
            "step_label": self.step_label,
            # Можно ли починить остановку кликом по скрину. Читает рецепт с
            # диска, поэтому только у задач, которые сейчас ждут.
            "repairable": self.status == HELD and self.held_kind not in ("blind", "lost")
                          and hold_repairable(self.scenario_key, self.step_index),
        }
        if self.error:
            d["error_info"] = explain(self.error)
        if with_log:
            d["timeline"] = [dict(t) for t in self.timeline]
            d["log"] = self.lines
        return d


def hold_repairable(scenario_key: str, step_index: int) -> bool:
    """Чинится ли остановленный шаг кликом по скрину (repair.js, режим hold).

    Зеркало repairPlan(..., 'hold'): шаг — click с селектором, и рендерится он
    в ctx.click_target (есть texts/crop/point, см. codegen._call). Иначе патч
    цели на лету задача не примет, и окно починки откроется только затем,
    чтобы сказать «нельзя». Проверка тут, а не в браузере: без неё кнопка
    «Указать на скрине» висела и там, где ей нечего предложить.
    """
    if not scenario_key or step_index < 0:
        return False
    steps = (recorder_save.load_recipe(scenario_key) or {}).get("steps") or []
    if step_index >= len(steps):
        return False
    step = steps[step_index]
    if not isinstance(step, dict) or step.get("kind") != "click" or not step.get("selector"):
        return False
    return bool(step.get("texts") or step.get("crop") or step.get("point")
                or step.get("point_rel"))


def _open_step(job: Job, index: int, labels: list) -> None:
    """Шаг `index` начался: закрыть предыдущий как выполненный, открыть новый."""
    now = time.time()
    if job.timeline and job.timeline[-1].get("t0") and "open" in job.timeline[-1]:
        last = job.timeline[-1]
        last["secs"] = round(last.get("secs", 0) + now - last.pop("open"), 2)
    job.step_index = index
    job.step_label = labels[index] if 0 <= index < len(labels) else ""
    # Повтор по кругу проходит одни и те же шаги сотни раз: запись шага одна,
    # с числом проходов и суммарным временем, — иначе журнал и отчёт росли бы
    # на каждом круге. Текущий шаг всегда последний в списке (см. _mark_step).
    for k, entry in enumerate(job.timeline):
        if entry["i"] == index:
            job.timeline.append(job.timeline.pop(k))
            entry["n"] = entry.get("n", 1) + 1
            entry["open"] = now
            return
    job.timeline.append({"i": index, "label": job.step_label,
                         "status": "ok", "t0": now, "open": now})
    job.add_line(f"▶ шаг {index + 1}/{job.step_total}: {job.step_label}")


def _mark_step(job: Job, status: str) -> None:
    """Пометить текущий шаг: retried/blind/skipped/failed (сильнейший статус остаётся)."""
    if not job.timeline:
        return
    rank = {"ok": 0, "retried": 1, "blind": 2, "skipped": 3, "failed": 4}
    cur = job.timeline[-1]
    if rank.get(status, 0) >= rank.get(cur["status"], 0):
        cur["status"] = status


def _finish_timeline(job: Job, art_dir: Path) -> None:
    """Закрыть последний шаг и положить отчёт `report.json` рядом с артефактами."""
    if not job.timeline:
        return
    last = job.timeline[-1]
    if "open" in last:
        last["secs"] = round(last.get("secs", 0) + time.time() - last.pop("open"), 2)
    job.timeline.sort(key=lambda t: t["i"])   # после повторов — снова по порядку шагов
    try:
        report = {"job": job.id, "scenario": job.scenario_name,
                  "device": job.device_name, "status": job.status,
                  "error": job.error,
                  "error_info": explain(job.error) if job.error else None,
                  "steps": [{k: v for k, v in t.items() if k != "t0"}
                            for t in job.timeline]}
        (art_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    except OSError as e:
        job.add_line(f"отчёт не записался: {e}")


def step_index_from_frames(frames, scenario_path, line_map: dict) -> int:
    """Индекс шага рецепта по кадрам стека; -1, если определить нельзя.

    Берётся самый внутренний кадр из файла сценария: кадры фермы глубже него
    (внутри ctx.click_target и т. п.) не важны — упавший шаг это строка
    сценария. Модуль грузится по `sc.path`, поэтому co_filename совпадает с
    ним; сравниваем разрешённые пути. Исключение не нужно — годится и
    `traceback.extract_stack()` (остановка HOLD идёт без исключения).
    """
    if not line_map:
        return -1
    цель = Path(scenario_path).resolve()
    for f in reversed(list(frames)):
        if Path(f.filename).resolve() == цель:
            return line_map.get(f.lineno, -1)
    return -1


def step_index_from_exc(exc: BaseException, scenario_path, line_map: dict) -> int:
    return step_index_from_frames(traceback.extract_tb(exc.__traceback__),
                                  scenario_path, line_map)


def verified_line_map(sc) -> dict:
    """Карта «строка .py → шаг» — только если она описывает код, который РЕАЛЬНО шёл.

    Сверяем `sc` (модуль, что исполнялся), а не свежий `scenarios.get` и не файл
    на диске в момент падения: правка руками, «выброшенный» сценарий, рецепт-сирота
    и сохранение конструктора посреди прогона иначе дали бы чужой шаг, а ремонт
    по нему испортил бы рабочий шаг. Условия: сценарий из конструктора, у рецепта
    есть `code_sha256` и он равен sha256 загруженных байт. Иначе {} (индекс -1).
    У старых рецептов ключа нет: ремонт им недоступен, пока конструктор не
    пересохранит их; снимок экрана при этом остаётся.
    """
    if sc is None or not getattr(sc, "recorded", False):
        return {}
    рецепт = recorder_save.load_recipe(sc.key) or {}
    ожидаемый = рецепт.get("code_sha256")
    if not ожидаемый:
        return _rebuilt_line_map(sc, рецепт)
    if ожидаемый != getattr(sc, "sha256", ""):
        return {}
    return recorder_save.load_line_map(sc.key)


def _rebuilt_line_map(sc, рецепт: dict) -> dict:
    """Карта для рецептов без code_sha256 (записаны до его появления).

    Доверие то же, что у хэша: рецепт заново прогоняется через кодоген, и карта
    отдаётся, только если получился ровно тот файл, что загружен (сравнение
    байт с sc.sha256). Правка руками или чужая версия рецепта дают {}.
    """
    try:
        m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", Path(sc.path).read_text("utf-8")[:200])
        if not m or not рецепт.get("steps"):
            return {}
        day = date(int(m[3]), int(m[2]), int(m[1]))
        items = recorder_steps.normalize_steps(рецепт["steps"])
        meta = рецепт.get("meta") or {}
        params = рецепт.get("params") or {}
        code, line_map = recorder_codegen.render_mapped(meta, params, items, day)
        if hashlib.sha256(code.encode("utf-8")).hexdigest() != getattr(sc, "sha256", ""):
            return {}
        return line_map
    except Exception:  # noqa: BLE001 — карта нужна только для показа хода
        return {}


def _record_failure(job: Job, art_dir: Path, step_index: int = -1,
                    miss: str = "") -> None:
    """Позвать человека к упавшей задаче.

    Журнал задач сам о себе не сообщает: на двадцати устройствах падение
    теряется среди сотни строк. Отклонение — одно на причину, со счётчиком по
    устройствам и с кнопкой обучения, если слепок преграды снялся.
    """
    слепок = art_dir / "obstacle.json"
    кадр = art_dir / "99_failure.jpg"
    try:
        dv.deviations.record(
            kind=dv.FAIL,
            title=job.error or "задача упала без сообщения",
            detail=f"Сценарий «{job.scenario_name}» остановился на "
                   f"{job.device_name}. Артефакты падения — в журнале задачи.",
            device_name=job.device_name,
            job_id=job.id,
            scenario_key=job.scenario_key,
            scenario_name=job.scenario_name,
            obstacle_file="obstacle.json" if слепок.is_file() else "",
            shot="99_failure.jpg" if кадр.is_file() else "",
            step_index=step_index,
            miss=miss,
            signature=job.error,
        )
    except Exception as e:  # noqa: BLE001 — запись не должна портить итог задачи
        job.add_line(f"отклонение о падении не записалось: {e}")


def _hold(job: Job, что: str, miss: str = "", sc=None, kind: str = "",
          obstacle: str = "") -> str:
    """Остановить задачу на промахнувшемся шаге и дождаться человека.

    Зовётся из шага сценария, то есть внутри `_execute`, — поэтому устройство
    остаётся занятым само, без отдельного захвата: `registry.release` стоит в
    `finally`, до которого мы ещё не дошли. Это и есть весь смысл остановки:
    экран на телефоне ещё тот, на котором споткнулись.

    Возвращает решение человека. DROP — «веди себя как раньше», и его же
    возвращают все отказы: занятый потолок, истёкшее ожидание, отмена.
    """
    # Вопрос про шаг вслепую: отказ его задать (потолок, таймаут) — это «иду
    # как раньше», а не падение: задачу роняет только сам человек.
    # «lost» — сторож долгого цикла: не шаг, а экран; прежняя метка шага ему не указ.
    слепой = kind != "lost" and bool(job.timeline and job.timeline[-1].get("status") == "blind")
    # Никто не ответил (потолок, таймаут): сторож идёт дальше, как листал раньше.
    отказ = HOLD_GO if слепой else HOLD_SKIP if kind == "lost" else HOLD_DROP
    занято = runner.held()
    if занято >= config.HOLD_MAX:
        job.add_line(f"ждут человека уже {занято} устройств — "
                     f"не останавливаюсь, {'иду дальше вслепую' if слепой else 'иду дальше как есть' if отказ == HOLD_SKIP else 'падаю'}")
        return отказ
    # «lost» — сторож долгого цикла: не шаг промахнулся, а экран не тот.
    job.held_kind = "blind" if слепой else kind
    job.held_obstacle = obstacle

    # Статус HELD — последним: увидев его, API-поток может сразу звать decide,
    # и к этому моменту сброс уже сделан, иначе он затёр бы ответ.
    job.decision = ""
    job.target_patch = None
    job._decided.clear()
    job.held_reason = что
    job.held_at = time.time()
    # Строка ожидания — до флипа: decide пишет «человек решил» сразу после HELD,
    # и запись после флипа могла оказаться в журнале позже неё.
    job.add_line(f"жду решения человека: {что}")
    job.status = HELD
    # Отмена, пришедшая между check_cancel шага и сбросом события выше,
    # уже поставила _decided — а сброс его стёр: задача проспала бы отмену
    # все HOLD_TIMEOUT в статусе HELD. cancel ставит _cancel раньше
    # _decided, поэтому этой проверки после сброса достаточно.
    if job._cancel.is_set():
        job._decided.set()
    else:
        _record_hold(job, что, miss, sc, obstacle)

    job._decided.wait(timeout=config.HOLD_TIMEOUT)
    # Чтение решения и возврат статуса — под замком decide: иначе ответ,
    # пришедший между таймаутом и флипом, получил бы ok=True от UI, а задача
    # всё равно упала бы, оставив висеть _decided и патч. После этого блока
    # статус уже не HELD, и опоздавший decide честно получит False.
    with runner._lock:
        приехали = job._decided.is_set()
        решение = job.decision or отказ
        if not приехали:
            job.add_line(f"никто не пришёл за {config.HOLD_TIMEOUT:.0f} с — "
                         f"{'иду дальше вслепую' if слепой else 'иду дальше как есть' if отказ == HOLD_SKIP else 'падаю'}")
        # Разбудить остановленную задачу могла и отмена — тогда статус ей уже
        # поставила `cancel`, и возврат в RUNNING его бы затёр.
        job.status = CANCELLING if job._cancel.is_set() else RUNNING
        job._decided.clear()
        # Патч живёт дальше только вместе с настоящим ответом человека: его
        # заберёт click_target через _take_patch. Таймаут/отмена — ответа нет.
        if not job.decision:
            job.target_patch = None
        job.held_reason = ""
        job.held_kind = ""
        job.held_obstacle = ""
        job.held_at = None
    # И ответ, и молчаливый таймаут одинаково снимают HELD — оба пути ведут
    # сюда, поэтому строка «ждёт» в «Отклонениях» гасится тут же, а не только
    # при decide(): иначе задача, брошенная без ответа, продолжала бы висеть
    # в списке с текстом «упадёт через 10 мин» уже после того, как упала.
    dv.deviations.resolve_hold(job.id)
    return решение


def _take_patch(job: Job) -> dict | None:
    """Отдать исправленную цель и забыть её: один ответ — один патч."""
    патч, job.target_patch = job.target_patch, None
    return патч


def _record_hold(job: Job, что: str, miss: str = "", sc=None, obstacle: str = "") -> None:
    """Отклонение «ждёт решения».

    Подпись включает задачу намеренно: остальные виды отклонений сливаются в
    одну строку на причину, а здесь наоборот — решение нужно каждой задаче
    своё, и слить две стоящие задачи в одну строку значило бы потерять одну
    из них вместе с устройством.
    """
    art_dir = Path(config.ARTIFACTS_DIR) / job.id
    n = 1
    while (art_dir / f"hold_{n}.jpg").exists():  # задачу могут держать не раз
        n += 1
    имя = f"hold_{n}.jpg"
    try:
        control.save_screenshot(job.serial, art_dir / имя)
    except Exception as e:  # noqa: BLE001 — фото не должно ломать остановку
        job.add_line(f"фото остановки не снялось: {e}")
    shot = имя if (art_dir / имя).is_file() else ""
    # job.artifacts обычно собирается один раз, в конце прогона (см. ниже
    # по файлу) — а решение retry/skip/drop принимают, пока задача ещё
    # HELD, и без этой строки снимок остановки был бы недоступен фронту
    # ровно тогда, когда он нужнее всего.
    if shot and shot not in job.artifacts:
        job.artifacts.append(shot)
    step_index = -1
    try:
        # sc — тот самый модуль, что исполняется (его передал _execute); без него
        # целостность не проверить, и индекс остаётся -1.
        if sc is not None:
            step_index = step_index_from_frames(
                traceback.extract_stack(), sc.path, verified_line_map(sc))
    except Exception as e:  # noqa: BLE001
        job.add_line(f"индекс шага не определён: {e}")
    try:
        dv.deviations.record(
            kind=dv.HOLD,
            title=f"запуск ждёт решения: {что}",
            detail=(f"«{job.scenario_name}» на {job.device_name} сбился с пути и ждёт. "
                    f"Покажите, как быть на этом экране, — ферма запомнит и продолжит. "
                    if obstacle else
                    f"«{job.scenario_name}» остановлен на {job.device_name}, экран держится. "
                    f"Поправьте экран и повторите шаг — или пропустите его. ")
                   + f"Без ответа запуск завершится через {config.HOLD_TIMEOUT / 60:.0f} мин.",
            device_name=job.device_name,
            job_id=job.id,
            scenario_key=job.scenario_key,
            scenario_name=job.scenario_name,
            shot=shot,
            step_index=step_index,
            miss=miss,
            obstacle_file=obstacle,
            signature=f"hold|{job.id}",
        )
    except Exception as e:  # noqa: BLE001 — запись не должна ломать остановку
        job.add_line(f"отклонение об остановке не записалось: {e}")


def _collect_failure_artifacts(job: Job, art_dir: Path) -> None:
    """При падении сохраняем всё, что поможет разобраться."""
    for label, fn in (
            ("скриншот", lambda: control.save_screenshot(job.serial, art_dir / "99_failure.jpg")),
            ("UI-дерево", lambda: (art_dir / "failure_hierarchy.xml").write_text(
                control.dump_hierarchy(job.serial), "utf-8")),
            ("logcat", lambda: (art_dir / "failure_logcat.txt").write_text(
                control.logcat_tail(job.serial, 500), "utf-8")),
            # Рамки в дампе — в пикселях устройства, а скриншот уменьшен:
            # без размера экрана разбор дампа по сохранённому кадру невозможен.
            ("размер экрана", lambda: (art_dir / "failure_size.json").write_text(
                json.dumps(dict(zip(("width", "height"), control.size(job.serial)))),
                "utf-8")),
            # Слепок преграды снимается здесь, а не когда человек откроет
            # журнал: к тому моменту устройство заберёт следующая задача.
            ("слепок преграды", lambda: (art_dir / "obstacle.json").write_text(
                json.dumps(obstacle.capture(
                    control.dump_hierarchy(job.serial),
                    *control.size(job.serial),
                    package=control.current_app(job.serial)),
                    ensure_ascii=False, indent=1), "utf-8")),
    ):
        try:
            fn()
            job.add_line(f"сохранён {label} падения")
        except Exception as e:  # noqa: BLE001
            job.add_line(f"не удалось снять {label}: {e}")


def _step_labels(sc) -> list:
    """Подписи шагов из рецепта; пусто у написанных руками сценариев."""
    if not getattr(sc, "recorded", False):
        return []
    рецепт = recorder_save.load_recipe(sc.key) or {}
    return [recorder_steps.label_of(st) for st in рецепт.get("steps", [])
            if isinstance(st, dict)]


def _execute(job: Job) -> None:
    # ждём освобождения устройства (например, оно отвалилось и переподключается)
    deadline = time.time() + 120
    while not registry.acquire(job.serial, job.id):
        if job._cancel.is_set():
            job.status = CANCELLED
            job.finished_at = time.time()
            return
        if time.time() > deadline:
            job.status = FAILED
            job.error = "устройство недоступно 2 минуты"
            job.add_line(job.error)
            job.finished_at = time.time()
            return
        time.sleep(1.0)

    # Отмена могла прийти ровно в тот круг, где устройство освободилось:
    # заняли — значит надо отпустить, а не начинать отменённый сценарий.
    if job._cancel.is_set():
        job.status = CANCELLED
        job.finished_at = time.time()
        job.add_line("отменено до старта")
        registry.release(job.serial, job.id)
        return

    job.status = RUNNING
    job.started_at = time.time()
    art_dir = Path(config.ARTIFACTS_DIR) / job.id
    sc = None
    # Всё, что может бросить (mkdir, scenarios.get при OSError), — внутри try:
    # устройство уже занято, и без finally оно осталось бы занятым навсегда,
    # а задача — вечно RUNNING.
    try:
        art_dir.mkdir(parents=True, exist_ok=True)
        job.add_line(f"старт «{job.scenario_name}» на {job.device_name}")
        sc = scenarios.get(job.scenario_key)
        if sc is None or sc.module is None:
            raise StepFailed("сценарий пропал или не загружается")

        ctx = DeviceContext(
            serial=job.serial,
            params=job.params,
            logger=job.add_line,
            cancel_check=job._cancel.is_set,
            artifacts_dir=art_dir,
            device_name=job.device_name,
            scenario_assets=Path(sc.path).with_name(f"{Path(sc.path).stem}_assets"),
            job_id=job.id,
            scenario_key=job.scenario_key,
            scenario_name=job.scenario_name,
            hold=lambda что, miss="", kind="", obstacle="": _hold(job, что, miss, sc, kind, obstacle),
            take_target_patch=lambda: _take_patch(job),
        )
        control.clear_logcat(job.serial)
        ctx.speed = job.speed
        module = sc.module
        line_map = verified_line_map(sc)
        labels = _step_labels(sc)
        # Без карты строк шаги не отслеживаются — «шаг 1/12» висел бы весь прогон.
        job.step_total = len(labels) if line_map else 0
        if job.stop_step is not None:
            module = stepflow.module_from_step(sc, line_map, job.start_step, job.stop_step)
            job.add_line(f"проверка шагов {job.start_step + 1}–{job.stop_step}: "
                         f"остальные пропущены")
        elif job.start_step:
            module = stepflow.module_from_step(sc, line_map, job.start_step)
            job.add_line(f"запуск с шага {job.start_step + 1}: предыдущие пропущены, "
                         f"экран должен быть в нужном состоянии")
        ctx.step_mark = lambda st: _mark_step(job, st)
        try:
            if line_map:
                with stepflow.StepTracer(module.run.__code__, line_map,
                                         lambda i: _open_step(job, i, labels)):
                    module.run(ctx)
            else:
                module.run(ctx)
        except Finished as e:
            job.add_line(f"сценарий закончен досрочно: {e}")
        job.status = PASSED
        job.add_line(f"готово за {job.duration:.1f} с")

    except Cancelled as e:
        job.status = CANCELLED
        job.error = str(e)
        job.add_line("отменено")
    except Exception as e:  # noqa: BLE001
        job.status = FAILED
        job.error = f"{type(e).__name__}: {e}"
        job.add_line("ОШИБКА " + job.error)
        _mark_step(job, "failed")
        if not isinstance(e, StepFailed):
            job.add_line(traceback.format_exc(limit=6))
        # Сначала артефакты, потом отклонение: оно ссылается на слепок
        # преграды, и до его записи ссылаться было бы не на что.
        _collect_failure_artifacts(job, art_dir)
        try:
            idx = (step_index_from_exc(e, sc.path, verified_line_map(sc))
                   if sc is not None else -1)
        except Exception as err:  # noqa: BLE001 — индекс шага не должен ломать запись
            job.add_line(f"индекс шага не определён: {err}")
            idx = -1
        _record_failure(job, art_dir, idx, getattr(e, "miss", "") or "")
    finally:
        job.finished_at = time.time()
        registry.release(job.serial, job.id)
        _finish_timeline(job, art_dir)
        job.artifacts = sorted(str(p) for p in art_dir.glob("*") if p.is_file())


class Runner:
    WORKER_IDLE = 300   # с простоя, после которых поток устройства закрывается

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        # Без maxlen: история обрезается в _prune и только по завершённым —
        # иначе запуск 40 × 200 вытеснял из журнала ещё не начатые задачи,
        # и воркер молча их пропускал.
        self.order: deque[str] = deque()
        self._queues: dict[str, queue.Queue] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def submit(self, scenario_key: str, serials: list[str], params: dict | None = None,
               repeat: int = 1, start_step: int = 0, speed: float = 1.0,
               stop_step: int | None = None, batch: str | None = None) -> list[Job]:
        sc = scenarios.get(scenario_key)
        if sc is None:
            raise ValueError(f"сценарий «{scenario_key}» не найден")
        if sc.error:
            raise ValueError(f"сценарий «{scenario_key}» не загружается: {sc.error.splitlines()[-1]}")
        resolved = scenarios.resolve_params(sc, params)
        start_step = int(start_step or 0)
        speed = float(speed or 1.0)
        if start_step < 0:
            raise ValueError("start_step не может быть отрицательным")
        if not 0.1 <= speed <= 1.0:
            raise ValueError("speed: от 0.1 до 1 (меньше — медленнее)")
        if stop_step is not None:
            stop_step = int(stop_step)
            if stop_step <= start_step:
                raise ValueError("stop_step должен быть больше start_step")
        if start_step or stop_step is not None:
            # Ошибку недоступности отдаём сразу в ответ на запуск, а не на
            # каждом устройстве по очереди.
            stepflow.module_from_step(sc, verified_line_map(sc), start_step, stop_step)

        batch = batch or uuid.uuid4().hex[:10]
        # Все устройства — до первой задачи: иначе неизвестный третий телефон
        # давал 400, а первые два уже работали, и повтор запуска их удваивал.
        devices = []
        for serial in serials:
            dev = registry.get(serial)
            if dev is None:
                raise ValueError(f"устройство {serial} не подключено")
            devices.append((serial, dev))
        created: list[Job] = []
        for serial, dev in devices:
            for _ in range(max(1, repeat)):
                job = Job(
                    id=uuid.uuid4().hex[:12],
                    scenario_key=sc.key,
                    scenario_name=sc.name,
                    serial=serial,
                    device_name=dev.name,
                    params=dict(resolved),
                    start_step=start_step,
                    stop_step=stop_step,
                    batch=batch,
                    speed=speed,
                )
                with self._lock:
                    self.jobs[job.id] = job
                    self.order.append(job.id)
                    # put под замком: воркер решает «очередь пуста — выхожу»
                    # под ним же, и задача не попадёт к уже уходящему потоку.
                    self._queue_for(serial).put(job.id)
                created.append(job)
                log.info("задача %s: %s → %s", job.id, sc.name, dev.name)
        with self._lock:
            self._prune()   # раз на запуск: проход по журналу, а не по задаче
        return created

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.status in DONE or job._cancel.is_set():
            return False
        job._cancel.set()
        # Остановленная задача спит на событии решения, а не на check_cancel:
        # без побудки она проспала бы отмену до самого HOLD_TIMEOUT.
        job._decided.set()
        if job.status == QUEUED:
            job.status = CANCELLED
            job.finished_at = time.time()
            job.add_line("отменено до старта")
        else:
            # Прервать чужой поток посреди шага нельзя, а показать, что отмена
            # принята, надо сразу: статус меняется здесь, до выхода сценария.
            job.status = CANCELLING
            job.held_reason = ""
            job.held_at = None
            job.add_line("отмена принята — прерываю на ближайшем шаге")
        return True

    def decide(self, job_id: str, decision: str,
               target: dict | None = None) -> bool:
        """Ответ человека остановленной задаче. False — задача не ждёт ответа.

        `target` — исправленная цель click_target, только вместе с «повторить».
        Проверяется до любого касания задачи: плохой запрос её не будит.
        """
        if decision not in HOLD_DECISIONS:
            raise ValueError(f"неизвестное решение «{decision}»")
        патч = normalize_target(target)
        if патч and decision != HOLD_RETRY:
            raise ValueError("цель можно прислать только с решением «повторить»")
        job = self.jobs.get(job_id)
        if job is None:
            return False
        with self._lock:  # двойной клик: второй ответ не должен затирать первый
            if job.status != HELD or job._decided.is_set():
                return False
            if decision == HOLD_GO and job.held_kind != "blind":
                raise ValueError("«продолжить как есть» — только для шага вслепую")
            job.decision = decision
            job.target_patch = патч or None
            job.add_line(f"человек решил: {HOLD_WORDS[decision]}")
            job._decided.set()
        return True

    def held(self) -> int:
        """Сколько устройств сейчас держат экран в ожидании человека."""
        return sum(1 for job in list(self.jobs.values()) if job.status == HELD)

    def cancel_all(self, serial: str | None = None) -> int:
        n = 0
        for job in list(self.jobs.values()):
            if job.status in ACTIVE and (serial is None or job.serial == serial):
                if self.cancel(job.id):
                    n += 1
        return n

    def delete(self, job_id: str) -> bool:
        """Убрать завершённую задачу из журнала. Работающую сначала отменяют."""
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.status in ACTIVE:
                return False
            self.jobs.pop(job_id, None)
            try:
                self.order.remove(job_id)
            except ValueError:
                pass
            return True

    def clear_finished(self, serial: str | None = None) -> int:
        """Очистить журнал от всех завершённых задач."""
        with self._lock:
            n = 0
            for jid, job in list(self.jobs.items()):
                if job.status in ACTIVE:
                    continue
                if serial and job.serial != serial:
                    continue
                self.jobs.pop(jid, None)
                try:
                    self.order.remove(jid)
                except ValueError:
                    pass
                n += 1
            return n

    def list_jobs(self, limit: int = 60, serial: str | None = None,
                  batch: str | None = None) -> list[dict]:
        with self._lock:
            ids = list(self.order)[::-1]
        out = []
        for jid in ids:
            job = self.jobs.get(jid)
            if job is None or (serial and job.serial != serial) or (batch and job.batch != batch):
                continue
            out.append(job.to_dict())
            if len(out) >= limit:
                break
        return out

    def scenario_stats(self, key: str, limit: int = 50) -> dict:
        """Итог последних прогонов сценария: сколько прошло, сколько упало.

        Считает только завершённые попытки (passed/failed) — очередь и
        текущий прогон исходу ещё не подведены, добавлять их в знаменатель
        нечестно.
        """
        with self._lock:
            ids = list(self.order)[::-1]
        passed = failed = 0
        seen = 0
        for jid in ids:
            job = self.jobs.get(jid)
            if job is None or job.scenario_key != key or job.status not in (PASSED, FAILED):
                continue
            if job.status == PASSED:
                passed += 1
            else:
                failed += 1
            seen += 1
            if seen >= limit:
                break
        return {"passed": passed, "failed": failed}

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def stats(self) -> dict:
        s = {QUEUED: 0, RUNNING: 0, HELD: 0, CANCELLING: 0,
             PASSED: 0, FAILED: 0, CANCELLED: 0}
        for job in self.jobs.values():
            s[job.status] = s.get(job.status, 0) + 1
        return s

    def _prune(self) -> None:
        """Держать в журнале не больше JOB_HISTORY задач, выбрасывая старейшие
        завершённые. Живые (очередь, работа, HELD) не трогаем никогда."""
        лишних = len(self.order) - config.JOB_HISTORY
        if лишних <= 0:
            return
        keep: deque[str] = deque()
        for jid in self.order:
            job = self.jobs.get(jid)
            if лишних > 0 and (job is None or job.status not in ACTIVE):
                self.jobs.pop(jid, None)
                лишних -= 1
                continue
            keep.append(jid)
        self.order = keep

    # ------------------------------------------------------------------ воркеры
    def _queue_for(self, serial: str) -> queue.Queue:
        with self._lock:
            q = self._queues.get(serial)
            if q is None:
                q = queue.Queue()
                self._queues[serial] = q
            t = self._workers.get(serial)
            if t is None or not t.is_alive():
                t = threading.Thread(target=self._worker, args=(serial, q), name=f"worker-{serial}", daemon=True)
                self._workers[serial] = t
                t.start()
            return q

    def _worker(self, serial: str, q: queue.Queue) -> None:
        while True:
            try:
                job_id = q.get(timeout=self.WORKER_IDLE)
            except queue.Empty:
                # Простаивал — поток закрывается. Решение под замком submit:
                # иначе задача, положенная в момент выхода, ждала бы вечно.
                with self._lock:
                    if q.empty():
                        if self._workers.get(serial) is threading.current_thread():
                            self._workers.pop(serial, None)
                        return
                continue
            job = self.jobs.get(job_id)
            if job is None or job.status != QUEUED:
                continue
            _execute(job)


runner = Runner()
