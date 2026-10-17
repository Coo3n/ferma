"""Человечные жесты: разброс точки тапа, кривые свайпы, посимвольный ввод.

Чистая математика вынесена в функции с параметром `rng` — тесты передают
`random.Random(seed)` и получают воспроизводимые числа без устройства.
Действия над устройством идут через u2 touch (down/move/up), при неудаче
откатываются на обычные control-функции — та же схема, что в fallback.py.
"""
from __future__ import annotations

import random
import time

from .fallback import via_u2
from .geometry import to_pixels
from . import input as raw_input

# Доля площади элемента, в которую разрешено попадать: центр ± 55% размера (больше разброса).
SPREAD = 0.55
# Длительность касания down→up, секунды.
TAP_HOLD = (0.04, 0.13)
# Задержка между символами при печати, секунды.
CHAR_DELAY = (0.06, 0.22)
# Сколько промежуточных точек у кривого свайпа.
SWIPE_POINTS = (8, 14)
# Вероятность промаха при первом клике (требуется второй).
MISS_CHANCE = 0.04
# Задержка между первым промахом и вторым кликом, секунды.
MISS_DELAY = (0.25, 0.6)
# Максимальный бенд свайпа (было 12%, теперь 18% для живее движений).
SWIPE_BEND = 0.18

_rng = random.Random()


# ------------------------------------------------------------------ математика

def point_in(x1: float, y1: float, x2: float, y2: float, rng=None) -> tuple[float, float]:
    """Точка внутри прямоугольника: гаусс вокруг центра, обрезан краями зоны.

    Сигма выбрана так, что почти все точки ложатся в центральные 70% элемента,
    но каждая — своя. Координаты в тех же единицах, что и вход.
    """
    rng = rng or _rng
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    hw, hh = (x2 - x1) / 2, (y2 - y1) / 2
    px = cx + rng.gauss(0, SPREAD / 2) * hw
    py = cy + rng.gauss(0, SPREAD / 2) * hh
    return (min(max(px, cx - hw * SPREAD), cx + hw * SPREAD),
            min(max(py, cy - hh * SPREAD), cy + hh * SPREAD))


def bezier(x1: float, y1: float, x2: float, y2: float, n: int, rng=None) -> list:
    """Квадратичная Безье с уведённой вбок контрольной точкой.

    Шаги распределены ease-in-out: палец разгоняется и тормозит, а не ползёт
    равномерно. Возвращает n точек включая конечную, без начальной.
    Большой бенд (до 18%) делает свайпы более живыми и неидеальными.
    """
    rng = rng or _rng
    dx, dy = x2 - x1, y2 - y1
    # Перпендикуляр к направлению жеста, увод до 18% длины.
    bend = rng.uniform(-SWIPE_BEND, SWIPE_BEND)
    mx, my = x1 + dx / 2 - dy * bend, y1 + dy / 2 + dx * bend
    out = []
    for i in range(1, n + 1):
        t = i / n
        t = t * t * (3 - 2 * t)  # smoothstep: медленно-быстро-медленно
        a, b = (1 - t) ** 2, 2 * (1 - t) * t
        out.append((a * x1 + b * mx + t * t * x2,
                    a * y1 + b * my + t * t * y2))
    return out


def pause_time(lo: float, hi: float, rng=None) -> float:
    """Пауза «подумал и нажал»: чаще ближе к минимуму, изредка длинная.

    Экспоненциальное распределение: обычно быстро, редко долго раздумывает.
    Редко: очень длинная пауза (заблудился, читал текст).
    """
    rng = rng or _rng
    span = max(hi - lo, 0.0)

    # Очень редко (1%) очень длинная пауза — типично человеческое "зависание"
    if rng.random() < 0.01:
        return hi

    return lo + span * min(rng.expovariate(3.0), 1.0)


# ------------------------------------------------------------------ жесты

def tap(serial: str, x: float, y: float, rng=None) -> None:
    """Тап с настоящей длительностью касания. Иногда промахивается и требуется второй клик."""
    rng = rng or _rng
    ax, ay = to_pixels(serial, x, y)
    hold = rng.uniform(*TAP_HOLD)

    # Редкий промах: первый клик чуть в стороне, второй точный
    is_miss = rng.random() < MISS_CHANCE
    if is_miss:
        miss_x = ax + rng.randint(-20, 20)
        miss_y = ay + rng.randint(-20, 20)

        def gesture(d):
            # Первый промах
            d.touch.down(miss_x, miss_y)
            time.sleep(hold)
            d.touch.up(miss_x, miss_y)
            # Пауза и второй (правильный) клик
            time.sleep(rng.uniform(*MISS_DELAY))
            d.touch.down(ax, ay)
            time.sleep(hold)
            d.touch.up(ax, ay)
    else:
        def gesture(d):
            d.touch.down(ax, ay)
            time.sleep(hold)
            d.touch.up(ax, ay)

    if via_u2(serial, gesture):
        return
    raw_input.tap(serial, x, y)


def swipe(serial: str, x1: float, y1: float, x2: float, y2: float,
          duration: float = 0.25, rng=None) -> None:
    """Свайп по кривой Безье с переменной скоростью и микропаузами.

    Палец движется неравномерно: ускоряется и замедляется, как человек.
    Иногда делает микропаузу посередине.
    """
    rng = rng or _rng
    ax1, ay1 = to_pixels(serial, x1, y1)
    ax2, ay2 = to_pixels(serial, x2, y2)
    n = rng.randint(*SWIPE_POINTS)
    path = bezier(ax1, ay1, ax2, ay2, n, rng)
    step_delay = max(duration, 0.1) / n

    def gesture(d):
        d.touch.down(ax1, ay1)
        # Микропауза перед началом свайпа (как будто палец "подготавливается")
        time.sleep(rng.uniform(0.05, 0.15))

        for i, (px, py) in enumerate(path):
            # Основная задержка между точками + вариативность
            delay = step_delay * rng.uniform(0.5, 1.6)
            # Редко: микропауза посередине свайпа
            if i == n // 2 and rng.random() < 0.1:
                delay += rng.uniform(0.08, 0.2)
            time.sleep(delay)
            d.touch.move(int(px), int(py))

        d.touch.up(int(path[-1][0]), int(path[-1][1]))

    if via_u2(serial, gesture):
        return
    raw_input.swipe(serial, x1, y1, x2, y2, duration)


def send_text(serial: str, value: str, clear: bool = False, rng=None) -> None:
    """Печать по символу с человеческими задержками.

    Кириллицу умеет u2. Между словами иногда более длинная пауза.
    Редко добавляет микропаузу в середине слова (человек обдумывает).
    """
    rng = rng or _rng

    def typing(d):
        if clear:
            d.clear_text()
        for i, ch in enumerate(value):
            d.send_keys(ch, clear=False)

            # Между словами (пробел) — чуть дольше пауза
            if ch == ' ':
                delay = rng.uniform(*CHAR_DELAY) * rng.uniform(1.5, 2.5)
            else:
                delay = rng.uniform(*CHAR_DELAY)

            # Очень редко: пауза в середине слова
            if i > 0 and i < len(value) - 1 and rng.random() < 0.02:
                delay += rng.uniform(0.1, 0.3)

            time.sleep(delay)

    if via_u2(serial, typing):
        return
    raw_input.text(serial, value, clear=clear)
