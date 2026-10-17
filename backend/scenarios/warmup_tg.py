"""Прогрев Telegram: листает список чатов и каналов, открывает случайный и читает

Без логинов и паролей: работает в уже открытом аккаунте. Если приложения
нет на телефоне, сценарий останавливается с понятной причиной.
"""
import importlib.util
from pathlib import Path


def _load_human():
    """scenarios/ не пакет: общий модуль грузим по пути рядом с файлом."""
    spec = importlib.util.spec_from_file_location(
        "farm_scenario__human", Path(__file__).with_name("_human.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


human = _load_human()

NAME = "Прогрев Telegram"
DESCRIPTION = "Листает список чатов и каналов, открывает случайный, читает и возвращается назад"
TEMPLATE = True

PARAMS = {
    "minutes": {"label": "Минут на телефон", "type": "number", "default": 10},
    "like_chance": {"label": "Вероятность лайка, % (в Telegram не нужна)", "type": "number", "default": 10,
                    "min": 0, "max": 30},
    "only_watch": {"label": "Только смотреть (в Telegram лайков нет)", "type": "bool", "default": False},
}

PACKAGES = ["org.telegram.messenger"]
TITLE = "Telegram"


def browse(ctx, rnd):
    """Шаг сеанса: чаще листаем список чатов, иногда заходим в случайный."""
    if rnd.random() < 0.35:
        ctx.tap(rnd.uniform(0.3, 0.7), rnd.uniform(0.25, 0.85))
        ctx.sleep(rnd.uniform(1.5, 3))
        for _ in range(rnd.randint(1, 4)):
            # в чате старые сообщения сверху — листаем вниз пальцем
            human.swipe_feed(ctx, rnd, up=False)
            ctx.sleep(rnd.uniform(1.5, 6))
        ctx.back()
        ctx.sleep(rnd.uniform(0.8, 2))
    else:
        human.swipe_feed(ctx, rnd, up=rnd.random() < 0.7)


def run(ctx):
    package = human.ensure_app(ctx, PACKAGES, TITLE)
    human.open_app(ctx, package, TITLE)
    human.feed_session(ctx, ctx.params["minutes"], 0, only_watch=True, swipe=browse,
                       package=package)
    ctx.home()
