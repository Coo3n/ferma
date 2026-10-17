"""Прогрев TikTok: смотрит ролики TikTok как человек: разное время просмотра, редкие лайки двойным касанием

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

NAME = "Прогрев TikTok"
DESCRIPTION = "Смотрит ролики TikTok как человек: разное время просмотра, редкие лайки двойным касанием"
TEMPLATE = True

PARAMS = {
    "minutes": {"label": "Минут на телефон", "type": "number", "default": 10},
    "like_chance": {"label": "Вероятность лайка, % (0–30)", "type": "number", "default": 10,
                    "min": 0, "max": 30},
    "only_watch": {"label": "Только смотреть, без лайков", "type": "bool", "default": False},
}

PACKAGES = ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"]
TITLE = "TikTok"


def like(ctx):
    """Двойное касание по ролику."""
    human.double_tap(ctx, 0.45, 0.45)
    return True


def run(ctx):
    package = human.ensure_app(ctx, PACKAGES, TITLE)
    human.open_app(ctx, package, TITLE)
    human.feed_session(ctx, ctx.params["minutes"], ctx.params["like_chance"],
                       only_watch=ctx.params["only_watch"], like=like,
                       package=package)
    ctx.home()
