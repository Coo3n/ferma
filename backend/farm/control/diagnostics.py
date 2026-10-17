"""Чтение состояния устройства: иерархия UI и системный лог."""
from __future__ import annotations

from .. import adb
from .fallback import from_u2

DUMP_PATH = "/sdcard/farm_ui.xml"
DUMP_TIMEOUT = 30
READ_TIMEOUT = 20
LOGCAT_TIMEOUT = 30


def dump_hierarchy(serial: str) -> str:
    """XML-дерево UI. Используется инспектором и артефактами падений."""
    xml = from_u2(serial, lambda d: d.dump_hierarchy())
    if xml is not None:
        return xml
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
