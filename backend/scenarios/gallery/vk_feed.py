"""Лента VK: листает, лайкает по шансу.

Кнопка лайка — `com.vkontakte.android:id/iv_likes` (из вашего записанного
сценария «VK like»). Комментарии, подписки и избранное отключены.
"""
import random

from farm import feed

NAME = "VK: лента с лайками"
DESCRIPTION = "Листает ленту VK с паузой, ставит лайки по шансу, соблюдая потолок за сутки."
PACKAGE = "com.vkontakte.android"
GALLERY = {"platform": "VK", "verified": False, "package": PACKAGE}
ALLOWED = ("like",)
PARAMS = {k: v for k, v in feed.feed_params(views=40).items()
          if k in ("profile", "views", "dwell_lo", "dwell_hi", "like", "cap_like")}
PARAMS["views"]["label"] = "Сколько экранов пролистать"


class VkUI(feed.FeedUI):
    def __init__(self, ctx, rng):
        self.ctx, self.rng = ctx, rng

    def ready(self):
        return self.ctx.current_app() == PACKAGE

    def perform(self, action, text=""):
        if action != "like":
            return False
        self.ctx.click_target(sel=[dict(resourceId=f"{PACKAGE}:id/iv_likes")],
                              at=(0.064, 0.718), timeout=4)
        return True

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(0.8)

    def recover(self):
        self.ctx.back()
        self.ctx.sleep(1)


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    fp = feed.from_params(ctx.params, label="VK", platform="vk", allowed=ALLOWED)
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("VK не открылся")
    feed.run_feed(ctx, VkUI(ctx, random.Random()), fp)
