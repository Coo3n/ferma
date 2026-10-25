"""YouTube Shorts: смотрит ролики, лайкает по шансу.

Лайк ищется по подписи «Мне нравится / like this video» — подпись зависит от
языка телефона, поэтому запасной вариант — точка справа. Не проверено.
"""
import random

from farm import feed

NAME = "YouTube Shorts: просмотр с лайками"
DESCRIPTION = "Открывает Shorts, смотрит ролики с паузой и ставит лайки по шансу."
PACKAGE = "com.google.android.youtube"
GALLERY = {"platform": "YouTube", "verified": False, "package": PACKAGE}
ALLOWED = ("like",)
PARAMS = {k: v for k, v in feed.feed_params(views=40).items()
          if k in ("profile", "views", "dwell_lo", "dwell_hi", "like", "cap_like", "words")}
LIKE_DESC = "(?i).*(like this video|нравится|лайк).*"


class ShortsUI(feed.FeedUI):
    def __init__(self, ctx, rng):
        self.ctx, self.rng = ctx, rng

    def open_shorts(self):
        ctx = self.ctx
        ctx.click_if_exists(timeout=4, descriptionMatches="(?i)shorts")

    def ready(self):
        return self.ctx.current_app() == PACKAGE

    def perform(self, action, text=""):
        if action != "like":
            return False
        self.ctx.click_target(sel=[dict(descriptionMatches=LIKE_DESC)], at=(0.93, 0.55), timeout=4)
        return True

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(1.2)

    def recover(self):
        self.ctx.back()
        self.ctx.sleep(1)


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    fp = feed.from_params(ctx.params, label="YouTube", platform="youtube", allowed=ALLOWED)
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("YouTube не открылся")
    ui = ShortsUI(ctx, random.Random())
    ui.open_shorts()
    feed.run_feed(ctx, ui, fp)
