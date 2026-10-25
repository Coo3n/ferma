"""Счётчики вызовов нейросети: на задачу и на сутки по всей ферме.

Каждый вызов стоит денег (облако) или GPU-времени, а ферма из сорока телефонов
способна промахиваться синхронно: без потолка один сломанный экран превратился
бы в сорок платных вызовов за минуту. По образцу farm/budget.py: один файл,
«посмотреть и занять» целиком под замком, иначе два потока прочитают 199 и
оба запишут 200, перескочив потолок.
"""
from __future__ import annotations

import json
import os
import uuid
import logging
import threading
from datetime import date, timedelta
from pathlib import Path

from .. import config

log = logging.getLogger("farm.vlm")

KEEP_DAYS = 14
_lock = threading.RLock()
_data: dict | None = None
_data_path: str = ""
_jobs: dict = {}     # job_id -> сколько вызовов уже сделано (в памяти)
_JOBS_CAP = 2000


def today() -> str:
    return date.today().isoformat()


def _load() -> dict:
    global _data, _data_path
    path = str(config.VLM_USAGE_FILE)
    if _data is None or path != _data_path:   # путь могли сменить (тесты)
        try:
            raw = json.loads(Path(path).read_text("utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as e:
            log.warning("счётчик нейросети не читается (%s) — счёт с нуля", e)
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        edge = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
        _data = {d: int(n) for d, n in raw.items() if isinstance(n, int) and d >= edge}
        _data_path = path
    return _data


def _save() -> None:
    path = Path(config.VLM_USAGE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Поддерживается один процесс фермы: межпроцессного замка нет. Имя
    # tmp уникальное, чтобы два потока не писали в один файл.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(_data, indent=1), "utf-8")
    os.replace(tmp, path)


def used_today() -> int:
    with _lock:
        return int(_load().get(today(), 0))


def reserve(job_key: str, max_per_job: int, max_per_day: int) -> tuple[bool, str]:
    """Занять один вызов. (можно ли, причина отказа по-русски).

    Занимаем ДО вызова, а не после: параллельные потоки иначе все прошли бы
    проверку и все позвали бы модель. Если ответа не было вовсе (сеть, таймаут,
    ошибка сервера) — вызывающий возвращает занятое через `refund`: мёртвая
    модель иначе выжигала бы суточный лимит впустую.
    """
    with _lock:
        data = _load()
        if job_key:
            if _jobs.get(job_key, 0) >= max_per_job:
                return False, f"в этой задаче уже {max_per_job} подсказок нейросети — это потолок"
        if int(data.get(today(), 0)) >= max_per_day:
            return False, f"за сутки уже {max_per_day} вызовов нейросети — это потолок"
        data[today()] = int(data.get(today(), 0)) + 1
        if job_key:
            if len(_jobs) >= _JOBS_CAP:
                for k in list(_jobs)[: _JOBS_CAP // 2]:
                    _jobs.pop(k, None)
            _jobs[job_key] = _jobs.get(job_key, 0) + 1
        _save()
        return True, ""


def refund(job_key: str) -> None:
    """Вернуть вызов, который не дошёл до модели. Счётчик не уходит ниже нуля."""
    with _lock:
        data = _load()
        if int(data.get(today(), 0)) > 0:
            data[today()] = int(data[today()]) - 1
        if job_key and _jobs.get(job_key, 0) > 0:
            _jobs[job_key] -= 1
        _save()


def reset_jobs() -> None:
    with _lock:
        _jobs.clear()
