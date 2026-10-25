"""Потолок действий за сутки: сколько ферма позволит сделать одному аккаунту.

Зачем отдельно от джиттера. Джиттер разносит действия по времени, но не
ограничивает их число: цикл на пятьсот кругов открутит пятьсот подписок,
и аккаунт сгорит ровно так же, только не спеша. Потолок ограничивает
количество.

Ключ — аккаунт, а не телефон: блокируют личность. Один телефон за сутки
может поработать под двумя аккаунтами, и общий счётчик на телефон
обманывал бы в обе стороны.

Счётчики живут в одном файле, а пишут в них сорок телефонов разом, поэтому
«посмотреть и увеличить» целиком под замком: иначе два телефона прочитают
49 и оба запишут 50, перескочив потолок.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path

from . import config

log = logging.getLogger("farm.budget")

BUDGET_FILE = config.DATA_DIR / "budget.json"

# Сколько дней истории держим. Нужна она для одного — показать человеку, что
# было вчера; месяцами это копить незачем.
KEEP_DAYS = 14

_lock = threading.RLock()
_data: dict | None = None


def today() -> str:
    return date.today().isoformat()


def _prune(data: dict) -> dict:
    edge = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    for key, days in list(data.items()):
        for day in [d for d in days if d < edge]:
            days.pop(day, None)
        if not days:
            data.pop(key, None)
    return data


def _load() -> dict:
    global _data
    if _data is None:
        try:
            raw = json.loads(Path(BUDGET_FILE).read_text("utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, json.JSONDecodeError) as e:
            # Счётчики — не данные человека, их потеря не беда: начинаем с
            # нуля, но вслух, чтобы «потолок не работает» не выглядело магией.
            log.warning("файл счётчиков не читается (%s) — счёт с нуля", e)
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        _data = _prune({k: v for k, v in raw.items() if isinstance(v, dict)})
    return _data


def _save() -> None:
    path = Path(BUDGET_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def used(key: str, name: str, day: str = "") -> int:
    """Сколько уже сделано за день (по умолчанию за сегодня)."""
    with _lock:
        return int((_load().get(key) or {}).get(day or today(), {}).get(name, 0))


def take(key: str, name: str, limit: int) -> tuple[bool, int]:
    """Занять одно действие. (можно ли, сколько стало/было).

    Потолок уже исчерпан — счётчик не растёт: иначе «сделано 73 из 50» в
    отчёте врало бы о том, сколько действий ферма допустила.
    """
    with _lock:
        data = _load()
        days = data.setdefault(key, {})
        counters = days.setdefault(today(), {})
        было = int(counters.get(name, 0))
        if было >= limit:
            return False, было
        counters[name] = было + 1
        _save()
        return True, было + 1


def state(key: str = "", day: str = "") -> dict:
    """Счётчики за день: {ключ: {название: сколько}} или один ключ."""
    with _lock:
        data = _load()
        day = day or today()
        if key:
            return dict((data.get(key) or {}).get(day) or {})
        return {k: dict(v.get(day) or {}) for k, v in data.items() if v.get(day)}


def reset(key: str, name: str = "") -> None:
    """Обнулить счётчик (человек разобрался с аккаунтом и хочет продолжить)."""
    with _lock:
        counters = (_load().get(key) or {}).get(today())
        if not counters:
            return
        if name:
            counters.pop(name, None)
        else:
            counters.clear()
        _save()
