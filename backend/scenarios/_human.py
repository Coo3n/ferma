"""Человеческое поведение для сценариев прогрева.

Файл начинается с «_» — ферма не показывает его в списке. Сценарии берут его
через load_human() (см. warmup_*.py): папка scenarios/ не пакет, и обычный
`import _human` там не работает.

Всё идёт через ctx и ctx.sleep — отмена задачи срабатывает в любой паузе.
"""
from __future__ import annotations

import random
import time

MAX_LIKE_CHANCE = 30


def session_seconds(minutes: float, rnd: random.Random) -> float:
    """Случайная длина сеанса: 85–100 % заданных минут, никогда не больше."""
    minutes = max(0.0, float(minutes or 0))
    return minutes * 60 * rnd.uniform(0.85, 1.0)


def clamp_chance(like_chance) -> float:
    """Проценты из формы → вероятность 0..0.30."""
    try:
        value = float(like_chance or 0)
    except (TypeError, ValueError):
        value = 0.0
    return max(0.0, min(MAX_LIKE_CHANCE, value)) / 100


def double_tap(ctx, x: float, y: float) -> None:
    """Двойной тап — лайк в Instagram/TikTok. Без humanize-пауз между тапами,
    иначе приложение увидит два одиночных."""
    ctx.check_cancel()
    d = getattr(ctx, "d", None)
    if d is not None and hasattr(d, "double_click"):
        w, h = ctx.size
        d.double_click(int(x * w) if x <= 1 else x, int(y * h) if y <= 1 else y, 0.08)
    else:
        ctx.tap(x, y)
        ctx.tap(x, y)


def swipe_feed(ctx, rnd: random.Random, up: bool = True) -> None:
    """Один свайп ленты: случайные длина, скорость, небольшой наклон."""
    x1 = rnd.uniform(0.35, 0.65)
    length = rnd.uniform(0.25, 0.55)
    y1 = rnd.uniform(0.62, 0.82)
    y2 = max(0.1, y1 - length)
    x2 = min(0.9, max(0.1, x1 + rnd.uniform(-0.06, 0.06)))
    duration = rnd.uniform(0.18, 0.6)
    if up:
        ctx.swipe(x1, y1, x2, y2, duration)
    else:
        ctx.swipe(x2, y2, x1, y1, duration)


def feed_session(ctx, minutes: float, like_chance=0, only_watch: bool = False,
                 like=None, rnd: random.Random | None = None, clock=time.monotonic,
                 swipe=None, package: str = "") -> dict:
    """Листать ленту `minutes` минут как человек.

    like(ctx) — как ставить лайк в этом приложении; вернуть True, если
    получилось. Лайк ставится с вероятностью like_chance % (не больше 30)
    и никогда — при only_watch. swipe(ctx, rnd) заменяет свайп ленты
    (например, для Telegram). package — своё приложение: сторож (ctx.on_track)
    раз в ~20 с проверяет, что оно впереди и лента листается, иначе зовёт
    человека. Вернуть счётчики для журнала.
    """
    rnd = rnd or random.Random()
    only_watch = str(only_watch).strip().lower() in ("true", "1", "да", "yes")
    chance = 0.0 if only_watch or like is None else clamp_chance(like_chance)
    budget = session_seconds(minutes, rnd)
    start = clock()
    stats = {"swipes": 0, "likes": 0, "reads": 0, "seconds": budget}
    while clock() - start < budget:
        ctx.check_cancel()
        left = budget - (clock() - start)
        # Смотрим пост: чаще коротко, иногда «зачитываемся».
        if rnd.random() < 0.12:
            pause = rnd.uniform(8, 25)
            stats["reads"] += 1
        else:
            pause = rnd.uniform(1.5, 6)
        ctx.sleep(min(pause, max(0.0, left)))
        if clock() - start >= budget:
            break
        if chance and rnd.random() < chance:
            try:
                if like(ctx):
                    stats["likes"] += 1
                    ctx.sleep(rnd.uniform(0.6, 1.8))
            except Exception as e:  # noqa: BLE001  лайк — не повод ронять прогрев
                if type(e).__name__ == "Cancelled":
                    raise
        # Изредка листнуть чуть назад — люди так делают.
        if rnd.random() < 0.07:
            swipe_feed(ctx, rnd, up=False)
        else:
            (swipe or swipe_feed)(ctx, rnd)
        stats["swipes"] += 1
        ctx.sleep(rnd.uniform(0.3, 1.2))
        if package and hasattr(ctx, "on_track"):
            ctx.on_track(package)
    ctx.log(f"сеанс: листаний {stats['swipes']}, лайков {stats['likes']}, "
            f"долгих пауз {stats['reads']}")
    return stats


def ensure_app(ctx, packages, title: str) -> str:
    """Первый установленный пакет из списка или ctx.fail понятным текстом."""
    installed = set(ctx.packages())
    for pkg in packages:
        if pkg in installed:
            return pkg
    ctx.fail(f"{title} не установлен на телефоне")
    return ""


def open_app(ctx, package: str, title: str) -> None:
    ctx.unlock()
    ctx.launch_app(package, stop_first=True)
    if not ctx.wait_app(package, timeout=20):
        ctx.fail(f"{title} не открылся")
    ctx.sleep(random.uniform(2, 4))
