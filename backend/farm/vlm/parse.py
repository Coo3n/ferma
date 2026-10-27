"""Разбор ответа модели. Устойчивый: вокруг JSON бывает болтовня и ```-ограды."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

# AutoGLM отвечает не JSON, а строкой do(action="Tap", element=[x,y]) после рассуждений.
# Уверенности в ней нет; берём фиксированную, чуть выше порога по умолчанию (0.6):
# настоящая защита здесь — проверка надписи под точкой в locate, не это число.
AUTOGLM_CONFIDENCE = 0.7
_DO_TAP = re.compile(r'do\(\s*action\s*=\s*"Tap"\s*,\s*element\s*=\s*\[\s*(-?\d+(?:\.\d+)?)\s*,'
                     r'\s*(-?\d+(?:\.\d+)?)\s*\]\s*\)')

# Qwen3-VL изредка ломает JSON: "x": [233, 124], "y": 124. Число после ключа читаем всё равно,
# но только когда строгий разбор не нашёл ответа; границы и уверенность проверяются так же.
_LOOSE = {k: re.compile(rf'"{k}"\s*:\s*\[?\s*(-?\d+(?:\.\d+)?)') for k in ("x", "y", "confidence")}
_NOT_FOUND = re.compile(r'"found"\s*:\s*false', re.I)


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


def _do_tap(text: str) -> Answer | None:
    """Последний do(action="Tap", element=[x,y]) в тексте: до него идут рассуждения."""
    found = _DO_TAP.findall(text)
    if not found:
        return None
    x, y = float(found[-1][0]), float(found[-1][1])
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None
    return Answer(x / 1000.0, y / 1000.0, AUTOGLM_CONFIDENCE, "ответ AutoGLM")


def _loose(text: str) -> Answer | None:
    if _NOT_FOUND.search(text):
        return None
    got = {k: _LOOSE[k].search(text) for k in _LOOSE}
    if not all(got.values()):
        return None
    x, y, c = (float(got[k].group(1)) for k in ("x", "y", "confidence"))
    if not (0 <= x <= 1000 and 0 <= y <= 1000 and 0 <= c <= 1):
        return None
    why = re.search(r'"why"\s*:\s*"([^"]*)', text)
    return Answer(x / 1000.0, y / 1000.0, c, (why.group(1) if why else "")[:300])


def parse(text: str) -> Answer | None:
    """Ответ «нашёл» → Answer; «не нашёл», мусор, нет полей, координаты вне 0..1000 → None.
    Понимает JSON и родной формат AutoGLM do(action="Tap", element=[x,y])."""
    text = str(text or "")
    for obj in _objects(text):
        if obj.get("found") is False:
            return None
        x, y, c = _num(obj.get("x")), _num(obj.get("y")), _num(obj.get("confidence"))
        if x is None or y is None or c is None:
            continue
        if not (0 <= x <= 1000 and 0 <= y <= 1000 and 0 <= c <= 1):
            return None
        return Answer(x / 1000.0, y / 1000.0, c, str(obj.get("why") or "")[:300])
    return _do_tap(text) or _loose(text)
