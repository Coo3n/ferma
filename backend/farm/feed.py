"""Общий движок ленты для готовых сюжетов: листает, ставит лайки по шансам.

Движок знает только порядок и время; как именно нажать «лайк» в TikTok или
VK, ему говорит маленький класс FeedUI, который пишет сам сюжет. Так шесть
сюжетов не повторяют цикл «пауза → действия → свайп».

Приёмы переняты из TikTok-скрипта Laixi: пауза на видео включает время
действий (видео занимает заданное время при любом числе лайков), между
действиями микропаузы, нет панели действий — только смотрим. Иначе, чем у
Laixi: комментарии выбираются случайно, а не по кругу, и у каждого действия
есть потолок за сутки.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, replace

from . import story

DEFAULT_CAPS = {"like": 200, "favorite": 100, "follow": 40, "comment": 30}
MAX_WORDS = 200


def feed_params(views: int = 30, actions: bool = True) -> dict:
    """PARAMS для сюжета-ленты: поля формы запуска, подписи простыми словами."""
    params = {
        "profile": {"label": "Как вести себя", "options": list(story.PROFILE_LABELS),
                    "default": story.DEFAULT_PROFILE_LABEL,
                    "help": "Тихий — редкие действия, Активный — чаще. Ниже можно уточнить"},
        "views": {"label": "Сколько видео посмотреть", "type": "number",
                  "default": views, "min": 1, "max": 1000},
        "dwell_lo": {"label": "Пауза на видео от, с", "type": "number", "default": "",
                     "help": "Пусто — как у выбранного профиля"},
        "dwell_hi": {"label": "Пауза на видео до, с", "type": "number", "default": ""},
    }
    if actions:
        params.update({
            "like": {"label": "Шанс лайка, %", "type": "number", "default": "", "min": 0, "max": 100},
            "comment": {"label": "Шанс комментария, %", "type": "number", "default": "", "min": 0, "max": 100},
            "favorite": {"label": "Шанс избранного, %", "type": "number", "default": "", "min": 0, "max": 100},
            "follow": {"label": "Шанс подписки, %", "type": "number", "default": "", "min": 0, "max": 100},
            "comments": {"label": "Фразы для комментариев (по строке)", "type": "textarea", "default": "",
                         "help": "Можно «{класс|супер|огонь}» — на каждом телефоне выпадет свой вариант"},
            "cap_like": {"label": "Не больше лайков за сутки", "type": "number",
                         "default": DEFAULT_CAPS["like"], "min": 0},
            "cap_favorite": {"label": "Не больше в избранное за сутки", "type": "number",
                             "default": DEFAULT_CAPS["favorite"], "min": 0},
            "cap_follow": {"label": "Не больше подписок за сутки", "type": "number",
                           "default": DEFAULT_CAPS["follow"], "min": 0},
            "cap_comment": {"label": "Не больше комментариев за сутки", "type": "number",
                            "default": DEFAULT_CAPS["comment"], "min": 0},
        })
    params["words"] = {"label": "Слова поиска (по строке)", "type": "textarea", "default": "",
                       "help": "Пусто — просто листать ленту без поиска"}
    return params


@dataclass
class FeedParams:
    views: int
    profile: story.Profile
    words: list
    comments: list
    caps: dict
    label: str
    platform: object      # платформа аккаунта для потолка или None
    allowed: tuple


def _cap(params, action):
    n = story._num(params.get(f"cap_{action}"))
    return DEFAULT_CAPS[action] if n is None else max(0, int(n))


def from_params(p, *, label, platform=None, allowed=story.ACTIONS, need_actions=True) -> FeedParams:
    """Параметры формы → FeedParams. Ошибки формы — ValueError с понятным текстом."""
    errors = story.validate(p, need_actions=need_actions and bool(allowed), allowed=allowed)
    if errors:
        raise ValueError("; ".join(errors))
    profile = story.resolve_profile(p.get("profile"), p)
    profile = replace(profile, **{a: 0.0 for a in story.ACTIONS if a not in allowed})
    views = story._num(p.get("views"))
    return FeedParams(
        views=int(views) if views is not None else 30,
        profile=profile,
        words=story.parse_lines(p.get("words"), MAX_WORDS),
        comments=story.parse_lines(p.get("comments"), MAX_WORDS),
        caps={a: _cap(p, a) for a in story.ACTIONS},
        label=label, platform=platform, allowed=tuple(allowed))


class FeedUI:
    """Что сюжет умеет делать на экране своей ленты."""

    def ready(self) -> bool:
        """Мы на ленте, а не в чужом экране."""
        return True

    def has_actions(self) -> bool:
        """На этом видео есть панель действий (не реклама, не подборка)."""
        return True

    def can(self, action: str) -> bool:
        """Действие возможно на этом видео (есть нужный значок). Проверяется ДО
        списания суточного потолка: он тратится только на выполнимое."""
        return True

    def perform(self, action: str, text: str = "") -> bool:
        """Сделать действие из story.ACTIONS; True — получилось."""
        raise NotImplementedError

    def next(self) -> None:
        """Перейти к следующему видео."""
        raise NotImplementedError

    def search(self, word: str) -> None:
        """Найти слово и открыть случайный результат."""

    def recover(self) -> None:
        """Выбраться на ленту из чужого экрана."""


def swipe_up(ctx, rng=None) -> None:
    """Свайп к следующему видео. Геометрия из Laixi (экран 1080×2280:
    старт x 500–800, y 1300–1600, финиш x 500–800, y 350–500, 1 с), но долями
    экрана: ферма работает на разных разрешениях."""
    rng = rng or random
    ctx.swipe(rng.uniform(0.46, 0.74), rng.uniform(0.57, 0.70),
              rng.uniform(0.46, 0.74), rng.uniform(0.15, 0.22),
              rng.uniform(0.35, 0.55))


def run_feed(ctx, ui: FeedUI, fp: FeedParams, rng=None, clock=time.monotonic) -> story.Tally:
    """Лента: `fp.views` видео; на каждом — действия по шансам и пауза до цели."""
    rng = rng or random
    tally = story.Tally()
    rotator = story.WordRotator(fp.words, fp.profile.change_every, rng)
    ctx.log(f"{fp.label}: {fp.views} видео, слов поиска {len(fp.words)}, "
            f"фраз {len(fp.comments)}")
    for i in ctx.loop(times=fp.views, watch=True):
        started = clock()
        target = rng.uniform(*fp.profile.dwell)
        if i:
            word = rotator.tick()
            if word:
                ctx.log(f"меняю слово поиска: «{word}»")
                ui.search(word)
                tally.add("searches")
        ctx.pause(1, 3)
        if not ui.ready():
            ui.recover()
            if not ui.ready():
                ctx.fail("экран не похож на ленту, выбраться не удалось")
        chosen = story.pick_actions(fp.profile, rng, fp.allowed) if ui.has_actions() else []
        for action in story.ACTIONS:
            if action not in chosen or fp.caps[action] <= 0:
                continue
            if action == "comment" and not fp.comments:
                continue
            if not ui.can(action):
                continue
            # Потолок берём ДО действия: исчерпан — сюжет заканчивается успехом
            # (BudgetReached), а пятьдесят первая подписка не случается.
            ctx.budget(f"{fp.label}: {story.ACTION_WORDS[action]}", fp.caps[action], fp.platform)
            text = ctx.phrase(rng.choice(fp.comments)) if action == "comment" else ""
            if ui.perform(action, text):
                tally.add(action)
            ctx.pause(1, 3)
        tally.add("views")
        ctx.sleep(story.dwell_left(target, clock() - started))
        ui.next()
        if tally.counts["views"] % 5 == 0:
            ctx.log(tally.line())
    ctx.log("итог: " + tally.line())
    return tally
