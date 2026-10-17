"""Пул подключений uiautomator2.

Первое подключение к устройству медленное (ставится apk-сервис), поэтому
соединения кэшируются, а неудача не считается фатальной — вызывающий код
откатывается на голый adb.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("farm.u2")

_clients: dict[str, object] = {}
_locks: dict[str, threading.Lock] = {}
_failed_until: dict[str, float] = {}
_global_lock = threading.Lock()

RETRY_AFTER = 60.0  # после неудачи не долбить устройство минуту


def _lock_for(serial: str) -> threading.Lock:
    with _global_lock:
        return _locks.setdefault(serial, threading.Lock())


def get(serial: str, force: bool = False):
    """Вернуть u2-клиент или None, если подключиться не удалось."""
    if not force:
        cached = _clients.get(serial)
        if cached is not None:
            return cached
        until = _failed_until.get(serial, 0)
        if until > time.time():
            return None

    with _lock_for(serial):
        if not force and _clients.get(serial) is not None:
            return _clients[serial]
        try:
            import uiautomator2 as u2
        except ImportError:
            log.warning("uiautomator2 не установлен — работаю только через adb")
            _failed_until[serial] = time.time() + 3600
            return None
        try:
            d = u2.connect(serial)
            d.info  # проверка живости
            _clients[serial] = d
            _failed_until.pop(serial, None)
            log.info("uiautomator2 подключён: %s", serial)
            return d
        except Exception as e:  # noqa: BLE001 — любые сбои сети/устройства
            log.warning("uiautomator2 %s: %s", serial, e)
            _clients.pop(serial, None)
            _failed_until[serial] = time.time() + RETRY_AFTER
            return None


_warming: set[str] = set()


def warm_async(serial: str) -> None:
    """Поднять соединение в фоне, не задерживая вызывающего. Пока оно
    поднимается, вызывающий идёт медленным путём через adb — один раз,
    а не всегда."""
    if serial in _clients or _failed_until.get(serial, 0) > time.time():
        return
    with _global_lock:
        if serial in _warming:
            return
        _warming.add(serial)

    def run():
        try:
            get(serial)
        finally:
            _warming.discard(serial)

    threading.Thread(target=run, daemon=True, name=f"u2-warm-{serial}").start()


def drop(serial: str) -> None:
    with _global_lock:
        _clients.pop(serial, None)
        _failed_until.pop(serial, None)


def drop_all() -> None:
    with _global_lock:
        _clients.clear()
        _failed_until.clear()


def is_connected(serial: str) -> bool:
    return serial in _clients
