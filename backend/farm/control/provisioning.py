"""Подготовка устройства к работе в ферме."""
from __future__ import annotations

from .. import adb

SETTINGS_TIMEOUT = 10

FARM_SETTINGS = [
    ("global", "window_animation_scale", "0"),
    ("global", "transition_animation_scale", "0"),
    ("global", "animator_duration_scale", "0"),
    ("global", "stay_on_while_plugged_in", "3"),
    ("system", "screen_off_timeout", "1800000"),
]


def _same_value(current: str, expected: str) -> bool:
    """Android отдаёт «0.0» там, где записывали «0». Сравниваем как числа."""
    current = (current or "").strip()
    if not current or current == "null":
        return False
    try:
        return float(current) == float(expected)
    except ValueError:
        return current == expected


def _read(serial: str, scope: str, name: str) -> str:
    try:
        return adb.shell(serial, ["settings", "get", scope, name],
                         timeout=SETTINGS_TIMEOUT).strip()
    except adb.AdbError:
        return ""


def pending_settings(serial: str) -> list[str]:
    """Настройки, которые ещё не применены. Пустой список — всё готово."""
    return [f"{scope}.{name}" for scope, name, value in FARM_SETTINGS
            if not _same_value(_read(serial, scope, name), value)]


def is_prepared(serial: str) -> bool:
    return not pending_settings(serial)


def prepare_for_farm(serial: str) -> list[str]:
    """Отключить анимации, держать экран включённым при зарядке. Без root."""
    applied = []
    for scope, name, value in FARM_SETTINGS:
        try:
            adb.shell(serial, ["settings", "put", scope, name, value],
                      timeout=SETTINGS_TIMEOUT)
            applied.append(f"{scope}.{name}={value}")
        except adb.AdbError as e:
            applied.append(f"{scope}.{name}: ОШИБКА {e}")
    return applied
