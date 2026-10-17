"""Общая схема отката: сначала uiautomator2, при неудаче — голый adb.

u2 быстрее и умеет селекторы, но соединение отваливается. Провал означает
сброс соединения из пула и повтор через `adb shell`.
"""
from __future__ import annotations

import logging

from ..devices import pool as u2pool

log = logging.getLogger("farm.control")


def via_u2(serial: str, action) -> bool:
    """Выполнить действие через u2. False — вызывающий обязан откатиться на adb."""
    device = u2pool.get(serial)
    if device is None:
        return False
    try:
        action(device)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("u2 не справился на %s, откат на adb: %s", serial, e)
        u2pool.drop(serial)
        return False


def from_u2(serial: str, action):
    """Получить значение через u2. None — вызывающий обязан откатиться на adb."""
    device = u2pool.get(serial)
    if device is None:
        return None
    try:
        return action(device)
    except Exception as e:  # noqa: BLE001
        log.debug("u2 не справился на %s, откат на adb: %s", serial, e)
        u2pool.drop(serial)
        return None
