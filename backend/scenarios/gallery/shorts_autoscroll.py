"""Автолистание шортсов: свайп вверх с паузой, без лайков и комментариев.

Из скрипта Laixi «自动上滑»: вертикальный свайп со случайными точками, пауза
7–20 с на ролик. Подходит для TikTok, YouTube Shorts и Reels — у всех лента
листается свайпом вверх.
"""
import random

from farm import feed, story

NAME = "Автолистание шортсов"
DESCRIPTION = "Листает вертикальную ленту (TikTok, YouTube Shorts, Reels) со случайной паузой на ролик."
GALLERY = {"platform": "Любая лента", "verified": False, "package": "com.zhiliaoapp.musically"}
ALLOWED = ()
PARAMS = {
    "package": {"label": "Приложение (пакет)", "default": "com.zhiliaoapp.musically",
                "help": "TikTok com.zhiliaoapp.musically, YouTube com.google.android.youtube, "
                        "Instagram com.instagram.android"},
    "views": {"label": "Сколько роликов", "type": "number", "default": 50, "min": 1, "max": 1000},
    "dwell_lo": {"label": "Пауза на ролик от, с", "type": "number", "default": 7, "min": 1},
    "dwell_hi": {"label": "Пауза на ролик до, с", "type": "number", "default": 20, "min": 2},
}


class ScrollUI(feed.FeedUI):
    def __init__(self, ctx, package, rng):
        self.ctx, self.package, self.rng = ctx, package, rng

    def ready(self):
        return self.ctx.current_app() == self.package

    def has_actions(self):
        return False

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(1.5)

    def recover(self):
        self.ctx.back()
        self.ctx.sleep(1)


def run(ctx):
    package = (ctx.params["package"] or "").strip()
    if not package:
        ctx.fail("не указан пакет приложения")
    form = {"views": ctx.params["views"], "dwell_lo": ctx.params["dwell_lo"],
            "dwell_hi": ctx.params["dwell_hi"]}
    fp = feed.from_params(form, label="Автолистание", allowed=ALLOWED, need_actions=False)
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    ctx.launch_app(package)
    if not ctx.wait_app(package, timeout=20):
        ctx.fail(f"{package} не открылся")
    feed.run_feed(ctx, ScrollUI(ctx, package, random.Random()), fp)
