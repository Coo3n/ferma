"""Захват сырых touch-событий с тачскрина через getevent — проверка того, что
жест реально прошёл через ядро (`/dev/input/eventX`), а не только через
инжект на уровне фреймворка.

И `adb shell input tap/swipe`, и клики uiautomator2 кладут событие сразу во
входную очередь `InputDispatcher` через `InputManager.injectInputEvent` /
`Instrumentation.sendPointerSync` — в обход `EventHub`, который читает
`/dev/input/eventX`. Поэтому у чисто программного тапа `getevent` в норме не
покажет НИ ОДНОГО сырого события, а у настоящего пальца — покажет всегда.
Это сильный и не всегда очевидный для операторов ферм сигнал именно потому,
что подделать его — не подкрутить параметр, а сменить весь механизм ввода
на инжект уровня ядра (uinput), что на порядок сложнее плоского `adb input`.

Работает не на всех устройствах и прошивках одинаково (права на узел ввода,
формат `getevent -pl` у разных OEM отличается) — при любой проблеме функции
тихо возвращают None, детектор в этом случае просто не учитывает сигнал.
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Callable

from .. import adb

_TOUCH_HINT = "ABS_MT_POSITION_X"
_ADD_DEVICE = re.compile(r"add device \d+: (/dev/input/event\d+)")


def find_touch_device(serial: str) -> str | None:
    """Ищет узел ввода тачскрина по `getevent -pl` (по наличию ABS_MT_POSITION_X)."""
    try:
        out = adb.shell(serial, ["getevent", "-pl"], timeout=10)
    except Exception:  # noqa: BLE001
        return None
    current = None
    for line in out.splitlines():
        line = line.strip()
        m = _ADD_DEVICE.match(line)
        if m:
            current = m.group(1)
        elif current and _TOUCH_HINT in line:
            return current
    return None


def trace_gesture(serial: str, perform: Callable[[], None], settle_s: float = 0.15) -> dict | None:
    """Ловит raw-события с тачскрина во время выполнения `perform()`.

    Возвращает {"n_samples": int} или None, если трассировку получить не
    удалось (нет узла, нет доступа, adb не найден, устройство недоступно).
    """
    node = find_touch_device(serial)
    if node is None:
        return None
    try:
        proc = subprocess.Popen(
            [adb.ADB, "-s", serial, "shell", "getevent", "-lt", node],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
    except Exception:  # noqa: BLE001
        return None

    out = None
    try:
        time.sleep(settle_s)
        perform()
        time.sleep(settle_s)
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        except Exception:  # noqa: BLE001
            pass

    if not out:
        return None
    n_samples = sum(1 for line in out.splitlines() if "ABS_MT_POSITION" in line)
    return {"n_samples": n_samples}
