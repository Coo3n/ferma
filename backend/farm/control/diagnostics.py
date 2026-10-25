"""Чтение состояния устройства: иерархия UI и системный лог."""
from __future__ import annotations

import logging
import time

from .. import adb, config
from ..devices import pool as u2pool

_log = logging.getLogger("farm.control")

DUMP_PATH = "/sdcard/farm_ui.xml"
DUMP_TIMEOUT = 30
READ_TIMEOUT = 20
LOGCAT_TIMEOUT = 30


_DEAD_MARKS = ("not connected", "service not available", "uiautomator not running",
               "connection refused", "connection reset", "remote end closed")
_TIMEOUT_MARKS = ("timeout", "timed out")


def _kind_of(error: Exception) -> str:
    """"dead" — сервис мёртв, "timeout" — завис, "other" — разовый сбой."""
    text = f"{type(error).__name__} {error}".lower()
    if any(m in text for m in _DEAD_MARKS):
        return "dead"
    if isinstance(error, TimeoutError) or any(m in text for m in _TIMEOUT_MARKS):
        return "timeout"
    return "other"


def fetch_with_retry(fetch, recovery, delays=None, recover_after=None,
                     sleep=time.sleep, note=None):
    """Дамп с лестницей повторов и лечением зависшего uiautomator.

    Зависший сервис отвечает ошибкой или молчит, и слепой повтор сразу же
    встаёт в очередь за брошенным запросом. Поэтому:
    - «not connected»/«service not available» — лечим сразу, пауза не поможет;
    - таймаут — устройство ещё обрабатывает прошлый запрос, повтор до лечения
      только удлинит очередь: лечим и пробуем ровно один раз, без лестницы;
    - прочее — лестница пауз, а после `recover_after` подряд провалов лечим.
    `recovery` и `sleep` снаружи, чтобы логика проверялась без телефона.
    """
    delays = tuple(config.DUMP_RETRY_DELAYS if delays is None else delays)
    recover_after = config.DUMP_RECOVER_AFTER if recover_after is None else recover_after
    fails = step = 0
    recovered = False

    def heal(why):
        nonlocal recovered
        recovered = True
        if note:
            note(why)
        recovery()

    while True:
        try:
            return fetch()
        except Exception as e:  # noqa: BLE001 — любой сбой клиента u2
            kind = _kind_of(e)
            fails += 1
            if kind in ("dead", "timeout"):
                if recovered:
                    raise
                heal("сервис не отвечает" if kind == "dead" else "дамп завис")
                continue
            if not recovered and fails >= recover_after:
                heal(f"{fails} провала подряд")
                continue
            if step >= len(delays):
                raise
            sleep(delays[step])
            step += 1


def recoveries(serial: str) -> int:
    """Сколько раз на устройстве перезапускали uiautomator — для здоровья."""
    return u2pool.recoveries(serial)


_loggers: dict = {}
_cancels: dict = {}      # serial -> check_cancel задачи (бросает Cancelled)
_dead_until: dict = {}   # serial -> время, до которого u2 считаем мёртвым


def bind_cancel(serial: str, check) -> None:
    """Привязать проверку отмены: паузы лестницы повторов станут отменяемыми."""
    if check is None:
        _cancels.pop(serial, None)
    else:
        _cancels[serial] = check


def _cancel_sleep(serial: str):
    def sleep(seconds):
        end = time.time() + seconds
        while time.time() < end:
            check = _cancels.get(serial)
            if check:
                check()
            time.sleep(max(0.0, min(0.2, end - time.time())))
    return sleep


def bind_log(serial: str, log) -> None:
    """Привязать к устройству журнал текущей задачи (None — отвязать).

    Сигнатуру dump_hierarchy(serial) менять нельзя: её подменяют в тестах и
    зовут из мест, где журнала задачи нет. Поэтому журнал приходит сбоку.
    """
    if log is None:
        _loggers.pop(serial, None)
    else:
        _loggers[serial] = log


def dump_hierarchy(serial: str) -> str:
    """XML-дерево UI. Используется инспектором и артефактами падений.

    О перезапуске сервиса пишем в журнал задачи, если он привязан
    (`bind_log`), иначе — в обычный logging.
    """
    log = _loggers.get(serial)
    if u2pool.get(serial) is not None and time.time() >= _dead_until.get(serial, 0.0):
        def fetch():
            d = u2pool.get(serial)
            if d is None:
                raise RuntimeError("u2 not connected")
            return d.dump_hierarchy()

        def recovery():
            u2pool.note_recovery(serial)
            u2pool.reset_uiautomator(serial)

        def note(why):
            msg = (f"uiautomator перезапущен ({why}), "
                   f"перезапусков на устройстве: {u2pool.recoveries(serial) + 1}")
            if log is not None:
                log(msg)
            else:
                _log.warning("%s: %s", serial, msg)

        try:
            return fetch_with_retry(fetch, recovery, note=note,
                                    sleep=_cancel_sleep(serial))
        except Exception as e:  # noqa: BLE001 — дальше голый adb
            if type(e).__name__ == "Cancelled":
                raise
            _dead_until[serial] = time.time() + config.DUMP_DEAD_TTL
            _log.debug("дамп через u2 не вышел на %s, откат на adb: %s", serial, e)
            u2pool.drop(serial)
    adb.shell(serial, ["uiautomator", "dump", DUMP_PATH], timeout=DUMP_TIMEOUT)
    return adb.exec_out(serial, ["cat", DUMP_PATH],
                        timeout=READ_TIMEOUT).decode("utf-8", "replace")


def logcat_tail(serial: str, lines: int = 400) -> str:
    try:
        return adb.raw(["logcat", "-d", "-t", str(lines)],
                       serial=serial, timeout=LOGCAT_TIMEOUT)
    except adb.AdbError as e:
        return f"logcat недоступен: {e}"


def clear_logcat(serial: str) -> None:
    try:
        adb.raw(["logcat", "-c"], serial=serial, timeout=15)
    except adb.AdbError:
        pass
