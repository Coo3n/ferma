"""Лента-прогрев TikTok: листает, лайкает, пишет комментарии по шансам.

Селекторы TikTok — по структуре экрана (как в скрипте Laixi): справа колонка
из пяти значков, внизу панель из пяти вкладок. Не проверено на вашем парке.
"""
import random

from farm import feed, story
from farm.ui import structure, tree

NAME = "TikTok: лента-прогрев"
DESCRIPTION = ("Листает ленту с паузой на видео, ставит лайки, добавляет в избранное, "
               "подписывается и пишет комментарии по шансам; меняет слова поиска.")
PACKAGE = "com.zhiliaoapp.musically"
GALLERY = {"platform": "TikTok", "verified": False, "package": PACKAGE}
ALLOWED = story.ACTIONS
PARAMS = feed.feed_params(views=30)

CLOSE_PANEL = (0.92, 0.075)   # тап над панелью комментариев закрывает её
SEARCH_ICON = (0.92, 0.075)


class TikTokUI(feed.FeedUI):
    def __init__(self, ctx, rng):
        self.ctx, self.rng = ctx, rng
        self.nodes, self.column = [], []

    def _scan(self):
        w, h = self.ctx.size
        self.nodes = tree.parse(self.ctx.dump_hierarchy(), w, h)
        self.column = structure.action_column(self.nodes)

    def _tap(self, node):
        self.ctx.tap(*structure.center(node))
        return True

    def go_home(self):
        self._scan()
        bar = structure.tab_bar(self.nodes)
        if bar:
            self._tap(bar[0])
            self.ctx.sleep(1.5)

    def ready(self):
        return self.ctx.current_app() == PACKAGE

    def has_actions(self):
        self._scan()
        return len(self.column) >= 5

    def can(self, action):
        if action == "favorite":
            return len(self.column) > 5
        if action == "follow":
            return structure.follow_plus(self.nodes, self.column) is not None
        return True

    def perform(self, action, text=""):
        col = self.column
        if action == "like":
            return self._tap(col[1])
        if action == "favorite":
            return self._tap(col[3]) if len(col) > 5 else False
        if action == "follow":
            plus = structure.follow_plus(self.nodes, col)
            return self._tap(plus) if plus is not None else False
        if action == "comment":
            return self._comment(col[2], text)
        return False

    def _comment(self, icon, text):
        ctx = self.ctx
        self._tap(icon)
        ctx.sleep(2)
        for _ in range(self.rng.randint(1, 3)):          # «читает» комментарии
            ctx.pause(1, 3)
            ctx.swipe(0.5, 0.75, 0.5, 0.45, 0.35)
        field = ctx.find(timeout=3, className="android.widget.EditText")
        if field is None:
            ctx.back()
            return False
        field.click()
        ctx.type(text)
        ctx.pause(2, 4)
        w, h = ctx.size
        send = structure.send_after_input(tree.parse(ctx.dump_hierarchy(), w, h))
        if send is None:
            ctx.back()
            ctx.back()
            return False
        self._tap(send)
        ctx.sleep(2)
        ctx.tap(*CLOSE_PANEL)
        return True

    def next(self):
        feed.swipe_up(self.ctx, self.rng)
        self.ctx.sleep(1.5)

    def search(self, word):
        ctx = self.ctx
        self.recover()
        ctx.tap(*SEARCH_ICON)
        ctx.sleep(1.5)
        field = ctx.find(timeout=5, className="android.widget.EditText")
        if field is None:
            ctx.back()
            return
        field.click()
        ctx.type(word, clear=True)
        ctx.key("enter")
        ctx.sleep(3)
        w, h = ctx.size
        tiles = structure.grid_tiles(tree.parse(ctx.dump_hierarchy(), w, h))
        if tiles:
            self._tap(self.rng.choice(tiles))
            ctx.sleep(2)
        else:
            ctx.back()

    def recover(self):
        for _ in range(5):
            if self.ctx.current_app() == PACKAGE and self.has_actions():
                return
            self.ctx.back()
            self.ctx.sleep(1)


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    fp = feed.from_params(ctx.params, label="TikTok", platform="tiktok", allowed=ALLOWED)
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("TikTok не открылся")
    ui = TikTokUI(ctx, random.Random())
    ui.go_home()
    feed.run_feed(ctx, ui, fp)
