"""Размер экрана и перевод координат."""
from __future__ import annotations

from .. import adb
from .fallback import from_u2

FALLBACK_SIZE = (1080, 1920)

_cache: dict[str, tuple[int, int]] = {}


def size(serial: str) -> tuple[int, int]:
    """Размер экрана в пикселях. Кэшируется до `forget_size`."""
    if serial in _cache:
        return _cache[serial]
    wh = adb.screen_size(serial)
    if not wh:
        info = from_u2(serial, lambda d: d.info)
        if info:
            wh = (info["displayWidth"], info["displayHeight"])
    _cache[serial] = wh or FALLBACK_SIZE
    return _cache[serial]


def forget_size(serial: str) -> None:
    _cache.pop(serial, None)


def to_pixels(serial: str, x: float, y: float) -> tuple[int, int]:
    """Доли 0..1 переводит в пиксели, целые координаты пропускает как есть."""
    if 0 <= x <= 1 and 0 <= y <= 1 and isinstance(x, float) and isinstance(y, float):
        w, h = size(serial)
        return int(round(x * w)), int(round(y * h))
    return int(x), int(y)
