"""Разбор ответа модели. Устойчивый: вокруг JSON бывает болтовня и ```-ограды."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Answer:
    x: float            # доли 0..1
    y: float
    confidence: float
    why: str = ""


def _objects(text: str):
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                yield obj
            i = text.find("{", end)
        except ValueError:
            i = text.find("{", i + 1)


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def parse(text: str) -> Answer | None:
    """Ответ «нашёл» → Answer; «не нашёл», мусор, нет полей, координаты вне 0..1000 → None."""
    for obj in _objects(str(text or "")):
        if obj.get("found") is False:
            return None
        x, y, c = _num(obj.get("x")), _num(obj.get("y")), _num(obj.get("confidence"))
        if x is None or y is None or c is None:
            continue
        if not (0 <= x <= 1000 and 0 <= y <= 1000 and 0 <= c <= 1):
            return None
        return Answer(x / 1000.0, y / 1000.0, c, str(obj.get("why") or "")[:300])
    return None
