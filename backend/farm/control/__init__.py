"""Действия над устройством.

Каждое действие сначала пробуется через uiautomator2, при недоступности
откатывается на `adb shell` — см. fallback.py.
"""
from .apps import (
    current_app, grant, install, launch_app, open_url, stop_app, uninstall,
)
from .capture import save_screenshot, screenshot
from .diagnostics import clear_logcat, dump_hierarchy, logcat_tail
from .geometry import forget_size, size, to_pixels
from .input import KEYCODES, key, long_tap, swipe, tap, text, unlock, wake
from . import humanize
from .provisioning import (
    FARM_SETTINGS, is_prepared, pending_settings, prepare_for_farm,
)
from .stability import wait_stable

__all__ = [
    "size", "forget_size", "to_pixels", "humanize",
    "tap", "long_tap", "swipe", "text", "key", "wake", "unlock", "KEYCODES",
    "launch_app", "stop_app", "open_url", "install", "uninstall", "grant",
    "current_app",
    "screenshot", "save_screenshot",
    "dump_hierarchy", "logcat_tail", "clear_logcat",
    "prepare_for_farm", "pending_settings", "is_prepared", "FARM_SETTINGS",
    "wait_stable",
]
