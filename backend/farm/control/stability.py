"""Ожидание, пока экран дорисуется.

Медленный девайс не успел отрисовать экран — клик уходит в пустоту. Два
одинаковых дампа иерархии подряд означают «дорисовано». dump и sleep
подменяются в тестах, поэтому модуль проверяется без устройства.
"""
from __future__ import annotations

import hashlib
import time

from .. import config
from .diagnostics import dump_hierarchy


def _fingerprint(xml: str) -> str:
    return hashlib.md5(xml.encode("utf-8", "replace")).hexdigest()


def wait_stable(serial: str, timeout: float | None = None,
                quiet: float | None = None, dump=None, sleep=time.sleep) -> bool:
    """True — экран стабилен; False — таймаут или дамп не снялся."""
    timeout = config.SETTLE_TIMEOUT if timeout is None else timeout
    quiet = config.SETTLE_QUIET if quiet is None else quiet
    dump = dump or (lambda: dump_hierarchy(serial))
    deadline = time.monotonic() + timeout
    try:
        last = _fingerprint(dump())
    except Exception:  # noqa: BLE001 — дамп не снялся, шагу не мешаем
        return False
    while time.monotonic() < deadline:
        sleep(quiet)
        try:
            current = _fingerprint(dump())
        except Exception:  # noqa: BLE001
            return False
        if current == last:
            return True
        last = current
    return False
