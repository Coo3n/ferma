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


# Сколько лучших точек корреляции разбирать на отдельные совпадения. Больше
# не нужно: на экране редко бывает больше десятка одинаковых иконок.
MAX_PEAKS = 200


def suppress(points, min_dx: float, min_dy: float) -> list:
    """Точки (cx, cy, score) → по одной на место: соседние пики одной иконки
    схлопываются в лучший. Чистая функция, без opencv."""
    kept: list = []
    for p in sorted(points, key=lambda p: -p[2]):
        if all(abs(p[0] - q[0]) >= min_dx or abs(p[1] - q[1]) >= min_dy for q in kept):
            kept.append(p)
    return kept


def pick(peaks, near=None):
    """Какое из совпадений нажимать. Чистая функция, без opencv.

    Одинаковых иконок на экране бывает несколько (лайки в ленте). Лучший
    балл среди почти одинаковых — случайность сжатия JPEG, а не признак
    нужной. Если известно место записи (`at` шага), берём ближайшее к нему —
    это и есть «нужен вот этот». Без места — лучший балл, как раньше.
    """
    if not peaks:
        return None
    if near is None:
        return max(peaks, key=lambda p: p[2])
    return min(peaks, key=lambda p: (p[0] - near[0]) ** 2 + (p[1] - near[1]) ** 2)


def crop_box(region, sw: int, sh: int):
    """Рамка в долях экрана → пиксели (x1, y1, x2, y2), обрезанные экраном.
    Чистая функция, без opencv."""
    x1 = max(0, min(sw, int(round(region[0] * sw))))
    y1 = max(0, min(sh, int(round(region[1] * sh))))
    x2 = max(x1, min(sw, int(round(region[2] * sw))))
    y2 = max(y1, min(sh, int(round(region[3] * sh))))
    return x1, y1, x2, y2


def find(screen_png: bytes, template_png: bytes, base_scale: float = 1.0,
         near=None, with_count: bool = False, region=None):
    """(cx, cy, score) в долях экрана — или None.

    Похожих мест больше одного — выбор делает `pick` (ближайшее к `near`).
    `with_count` добавляет четвёртым числом, сколько похожих мест нашлось.
    `region` — рамка (x1, y1, x2, y2) в долях экрана: искать только в ней
    («внутри» контейнера). Ответ всё равно в долях всего экрана.
    """
    import cv2
    import numpy as np

    screen = cv2.imdecode(np.frombuffer(screen_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    original = cv2.imdecode(np.frombuffer(template_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if screen is None or original is None:
        return None
    full_h, full_w = screen.shape[:2]
    ox = oy = 0
    if region is not None:
        ox, oy, x2, y2 = crop_box(region, full_w, full_h)
        screen = screen[oy:y2, ox:x2]
        if screen.size == 0:
            return None
    sh, sw = screen.shape[:2]
    points = []
    min_dx = min_dy = 1.0
    for scale in scales_for(base_scale):
        w = int(original.shape[1] * scale)
        h = int(original.shape[0] * scale)
        if w < MIN_SIDE or h < MIN_SIDE or w > sw or h > sh:
            continue
        tpl = cv2.resize(original, (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= THRESHOLD)
        if not len(xs):
            continue
        order = np.argsort(-res[ys, xs])[:MAX_PEAKS]
        for i in order:
            x, y = int(xs[i]), int(ys[i])
            points.append(((ox + x + w / 2) / full_w, (oy + y + h / 2) / full_h,
                           float(res[y, x])))
        min_dx, min_dy = min(min_dx, w / 2 / full_w), min(min_dy, h / 2 / full_h)
    peaks = suppress(points, min_dx, min_dy)
    best = pick(peaks, near)
    if not best:
        return None
    return (*best, len(peaks)) if with_count else best
