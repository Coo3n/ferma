"""Ввод: касания, жесты, текст, аппаратные клавиши."""
from __future__ import annotations

import re
import shlex
import time

from .. import adb
from .fallback import via_u2
from .geometry import to_pixels

KEYCODES = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "recents": "KEYCODE_APP_SWITCH",
    "power": "KEYCODE_POWER",
    "enter": "KEYCODE_ENTER",
    "delete": "KEYCODE_DEL",
    "tab": "KEYCODE_TAB",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "menu": "KEYCODE_MENU",
    "search": "KEYCODE_SEARCH",
    "camera": "KEYCODE_CAMERA",
    "wake": "KEYCODE_WAKEUP",
    "sleep": "KEYCODE_SLEEP",
}

_CLEAR_PRESSES = 60


def tap(serial: str, x: float, y: float) -> None:
    ax, ay = to_pixels(serial, x, y)
    if via_u2(serial, lambda d: d.click(ax, ay)):
        return
    adb.shell(serial, ["input", "tap", str(ax), str(ay)])


def long_tap(serial: str, x: float, y: float, duration: float = 0.8) -> None:
    ax, ay = to_pixels(serial, x, y)
    if via_u2(serial, lambda d: d.long_click(ax, ay, duration)):
        return
    adb.shell(serial, ["input", "swipe", str(ax), str(ay), str(ax), str(ay),
                       str(int(duration * 1000))])


def swipe(serial: str, x1: float, y1: float, x2: float, y2: float,
          duration: float = 0.25) -> None:
    ax1, ay1 = to_pixels(serial, x1, y1)
    ax2, ay2 = to_pixels(serial, x2, y2)
    if via_u2(serial, lambda d: d.swipe(ax1, ay1, ax2, ay2, duration)):
        return
    adb.shell(serial, ["input", "swipe", str(ax1), str(ay1), str(ax2), str(ay2),
                       str(int(duration * 1000))])


def _send_text_via_u2(device, value: str, clear: bool) -> None:
    if clear:
        device.clear_text()
    device.send_keys(value, clear=False)


def text(serial: str, value: str, clear: bool = False) -> None:
    """Ввод текста. Юникод и кириллицу умеет только u2, `adb input text` — нет."""
    if via_u2(serial, lambda d: _send_text_via_u2(d, value, clear)):
        return
    if clear:
        adb.shell(serial, ["input", "keyevent", "KEYCODE_MOVE_END"])
        adb.shell(serial, "input keyevent " + " ".join(["KEYCODE_DEL"] * _CLEAR_PRESSES))
    _input_text(serial, value.replace(" ", "%s"))


def _input_text(serial: str, value: str) -> None:
    """`input text` через shell телефона: строка одним аргументом в кавычках.

    adb склеивает аргументы через пробел и отдаёт их sh на телефоне, так что
    & ; $ ` в пароле из accounts.json иначе стали бы командами. Текст ошибки
    adb содержит всю команду — значение из него вырезается, чтобы пароль не
    уехал в журнал задачи.
    """
    quoted = shlex.quote(value)
    try:
        adb.shell(serial, ["input", "text", quoted])
    except adb.AdbError as e:
        msg = str(e)
        for secret in {quoted, value}:
            if secret:
                msg = msg.replace(secret, "***")
        raise adb.AdbError(msg) from None


# Имя клавиши уходит в sh телефона (`input keyevent …`): «KEYCODE_HOME; reboot»
# раньше проходило проверку префикса и исполнялось целиком.
_KEYCODE_RE = re.compile(r"KEYCODE_[A-Z0-9_]{1,40}")


def _keycode(name: str) -> str:
    name = str(name or "")
    code = KEYCODES.get(name.lower())
    if code:
        return code
    if _KEYCODE_RE.fullmatch(name.upper()):
        return name.upper()
    raise ValueError(f"неизвестная клавиша: {name}")


# Имена, которые u2.press понимает сам. Неизвестное имя агент молча
# игнорирует (возвращает false без ошибки) — так «Недавние» ничего не делали.
_U2_PRESS = {
    "back": "back", "home": "home", "recents": "recent", "enter": "enter",
    "delete": "delete", "up": "up", "down": "down", "left": "left",
    "right": "right", "menu": "menu", "search": "search", "camera": "camera",
    "power": "power", "volume_up": "volume_up", "volume_down": "volume_down",
}


def _u2_key_name(name: str) -> str | None:
    return _U2_PRESS.get(str(name or "").lower())


def key(serial: str, name: str) -> None:
    code = _keycode(name)
    short = _u2_key_name(name)
    if short and via_u2(serial, lambda d: d.press(short)):
        return
    adb.shell(serial, ["input", "keyevent", code])


def wake(serial: str) -> None:
    adb.shell(serial, ["input", "keyevent", "KEYCODE_WAKEUP"])


def unlock(serial: str, pin: str | None = None) -> None:
    """Разбудить и смахнуть шторку блокировки. С PIN — ввести его."""
    wake(serial)
    time.sleep(0.4)
    swipe(serial, 0.5, 0.8, 0.5, 0.2, 0.2)
    if not pin:
        return
    time.sleep(0.6)
    _input_text(serial, str(pin))
    adb.shell(serial, ["input", "keyevent", "KEYCODE_ENTER"])
