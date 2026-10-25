"""Разрешение и плотность экрана: разбор `wm size`/`wm density` и команды.

Чистый модуль: ни adb, ни диска. Зачем: записанные клики и сценарии на долях
экрана попадают в одни и те же места, только если у всех телефонов одинаковые
размер и плотность. Смена обратима (`wm size reset`), поэтому её можно
пробовать.
"""
from __future__ import annotations

import re
from collections import Counter

MIN_SIDE, MAX_SIDE = 320, 4000
MIN_DPI, MAX_DPI = 80, 800

_SIZE = re.compile(r"(Physical|Override) size:\s*(\d+)x(\d+)", re.I)
_DENSITY = re.compile(r"(Physical|Override) density:\s*(\d+)", re.I)

RESET_COMMANDS = ("wm size reset", "wm density reset")


def parse_wm_size(out) -> dict:
    """Вывод `wm size`: физический размер, подмена (override) и действующий."""
    found = {kind.lower(): (int(w), int(h)) for kind, w, h in _SIZE.findall(out or "")}
    physical, override = found.get("physical"), found.get("override")
    return {"physical": physical, "override": override, "current": override or physical}


def parse_density(out) -> dict:
    """Вывод `wm density`: то же, что parse_wm_size, но числом."""
    found = {kind.lower(): int(v) for kind, v in _DENSITY.findall(out or "")}
    physical, override = found.get("physical"), found.get("override")
    return {"physical": physical, "override": override, "current": override or physical}


def _int(value, what):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ValueError(what)


def size_command(width, height) -> str:
    text = f"ширина и высота — числа от {MIN_SIDE} до {MAX_SIDE}"
    w, h = _int(width, text), _int(height, text)
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
        raise ValueError(text)
    return f"wm size {w}x{h}"


def density_command(dpi) -> str:
    text = f"плотность — число от {MIN_DPI} до {MAX_DPI}"
    n = _int(dpi, text)
    if not MIN_DPI <= n <= MAX_DPI:
        raise ValueError(text)
    return f"wm density {n}"


def fit_height(width, height, new_width) -> int:
    """Высота при новой ширине с теми же пропорциями; чётная, как требует экран."""
    return int(round(new_width * height / width / 2.0)) * 2


def summarize(sizes) -> list:
    """Сколько телефонов с каждым размером — по убыванию. None пропускается."""
    counts = Counter(tuple(s) for s in sizes if s)
    return [{"size": size, "count": n} for size, n in counts.most_common()]
