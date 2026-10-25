"""Сравнение двух кадров экрана: изменилось ли что-то после нажатия.

Чистая функция без adb. cv2/numpy необязательны, как у шаблонного слоя: нет
их — отвечаем None («не знаю»), и вызывающий этот шаг пропускает.
"""
from __future__ import annotations

# Доля пикселей, которые должны отличаться, чтобы кадры считались разными.
# Шум JPEG и мигающий курсор дают сотые доли процента, настоящая смена экрана
# или всплывшая подсказка — заметно больше.
CHANGED_SHARE = 0.002
# Разница яркости, с которой пиксель считается другим (шум сжатия ниже).
PIXEL_DELTA = 25
# Верхняя полоса кадра (строка состояния с часами) не сравнивается: часы
# меняются сами и выдавали бы «эффект» там, где его не было.
SKIP_TOP = 0.04


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def frames_differ(before: bytes, after: bytes, share: float = CHANGED_SHARE):
    """True — кадры различаются, False — одинаковы, None — сравнить нечем."""
    if not before or not after or not available():
        return None
    import cv2
    import numpy as np
    try:
        a = cv2.imdecode(np.frombuffer(before, np.uint8), cv2.IMREAD_GRAYSCALE)
        b = cv2.imdecode(np.frombuffer(after, np.uint8), cv2.IMREAD_GRAYSCALE)
    except Exception:  # noqa: BLE001 — битый кадр: сравнивать нечего
        return None
    if a is None or b is None:
        return None
    if a.shape != b.shape:
        return True      # размер экрана сменился (поворот) — это уже эффект
    top = int(a.shape[0] * SKIP_TOP)
    a, b = a[top:], b[top:]
    changed = np.count_nonzero(cv2.absdiff(a, b) > PIXEL_DELTA)
    return changed / max(1, a.size) > share
