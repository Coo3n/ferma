"""Действия над устройством.

Каждое действие сначала пробуется через uiautomator2, при недоступности
откатывается на `adb shell` — см. fallback.py.
"""
from .apps import (
    close_recent, current_app, grant, install, launch_app, open_url, recent_packages, stop_app, uninstall,
)
from .capture import is_blank, is_secure, save_screenshot, screenshot
from .diagnostics import bind_cancel, bind_log, clear_logcat, dump_hierarchy, logcat_tail, recoveries
from .geometry import forget_size, size, to_pixels
from .input import KEYCODES, key, long_tap, swipe, tap, text, unlock, wake
from . import humanize
from .provisioning import (
    FARM_SETTINGS, is_prepared, pending_settings, prepare_for_farm,
)
from .stability import wait_stable, wait_target_stable

__all__ = [
    "size", "forget_size", "to_pixels", "humanize",
    "tap", "long_tap", "swipe", "text", "key", "wake", "unlock", "KEYCODES",
    "launch_app", "stop_app", "recent_packages", "close_recent", "open_url", "install", "uninstall", "grant",
    "current_app",
    "screenshot", "save_screenshot",
    "dump_hierarchy", "bind_log", "bind_cancel", "recoveries", "is_secure", "is_blank", "logcat_tail", "clear_logcat",
    "prepare_for_farm", "pending_settings", "is_prepared", "FARM_SETTINGS",
    "wait_stable",
    "wait_target_stable",
]
