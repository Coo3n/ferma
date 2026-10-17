"""Поиск кропа на экране: OpenCV matchTemplate на нескольких масштабах.

Базовый масштаб — отношение ширины экрана прогона к ширине экрана записи (его
даёт meta.json папки ассетов). Вокруг базового перебираются ×0.85, ×1.0, ×1.15,
диапазон обрезан 0.7–1.3: дальше начинается мусор.
"""
from __future__ import annotations

SCALE_STEPS = (0.85, 1.0, 1.15)
SCALE_MIN, SCALE_MAX = 0.7, 1.3
THRESHOLD = 0.85
MIN_SIDE = 8  # шаблон меньше 8 px после масштабирования ищет что попало


def scales_for(base_scale: float) -> list[float]:
    """Масштабы для перебора — чистая функция, проверяется без opencv.

    Клэмп ограничивает шаг (±15%), а не итоговый масштаб: иначе на
    base_scale, далёком от 1.0 (запись на 720p, прогон на 1080p — рядовая
    пара устройств фермы), сам base_scale обрезается диапазоном 0.7–1.3 и
    никогда не пробуется, а на большом расхождении экранов слой мёртв
    (три одинаковых прогона подряд).
    """
    return [base_scale * min(max(step, SCALE_MIN), SCALE_MAX) for step in SCALE_STEPS]


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def find(screen_png: bytes, template_png: bytes, base_scale: float = 1.0):
    """(cx, cy, score) в нормализованных координатах — или None."""
    import cv2
    import numpy as np

    screen = cv2.imdecode(np.frombuffer(screen_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    original = cv2.imdecode(np.frombuffer(template_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if screen is None or original is None:
        return None
    best = None
    for scale in scales_for(base_scale):
        w = int(original.shape[1] * scale)
        h = int(original.shape[0] * scale)
        if w < MIN_SIDE or h < MIN_SIDE or w > screen.shape[1] or h > screen.shape[0]:
            continue
        tpl = cv2.resize(original, (w, h), interpolation=cv2.INTER_AREA)
        _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(screen, tpl,
                                                           cv2.TM_CCOEFF_NORMED))
        if score >= THRESHOLD and (best is None or score > best[2]):
            best = ((loc[0] + w / 2) / screen.shape[1],
                    (loc[1] + h / 2) / screen.shape[0],
                    float(score))
    return best
