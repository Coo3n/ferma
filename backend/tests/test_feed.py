"""Движок ленты на фейковых ctx и FeedUI: порядок, бюджет времени, поиск, потолки."""
import random

import pytest

from farm import feed, story
from farm.context import BudgetReached, StepFailed


class FakeCtx:
    def __init__(self):
        self.now = 0.0
        self.logs = []
        self.sleeps = []
        self.budgets = {}
        self.limits = {}
        self.params = {}

    def log(self, m):
        self.logs.append(m)

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s

    def pause(self, lo=0.4, hi=1.5):
        pass                      # паузы микро; время в тестах двигают только sleep и действия

    def phrase(self, t):
        return t

    def fail(self, m):
        raise StepFailed(m)

    def loop(self, times=None, minutes=None, pause=None, watch=False):
        for i in range(times):
            yield i

    def budget(self, name, limit, platform=None):
        self.budgets[name] = self.budgets.get(name, 0) + 1
        self.limits[name] = limit
        if self.budgets[name] > limit:
            raise BudgetReached(f"потолок: {name}")


class FakeUI(feed.FeedUI):
    def __init__(self, ctx, action_cost=4.0, ready=True, actions=True):
        self.ctx, self.cost = ctx, action_cost
        self._ready, self._actions = ready, actions
        self.performed, self.texts, self.searched = [], [], []
        self.nexts = self.recovers = 0

    def ready(self):
        return self._ready

    def has_actions(self):
        return self._actions

    def perform(self, action, text=""):
        self.performed.append(action)
        self.texts.append(text)
        self.ctx.now += self.cost
        return True

    def next(self):
        self.nexts += 1

    def search(self, word):
        self.searched.append(word)

    def recover(self):
        self.recovers += 1


def fp(**kw):
    prof = story.Profile(kw.pop("like", 0), kw.pop("comment", 0), kw.pop("favorite", 0),
                         kw.pop("follow", 0), kw.pop("dwell", (10.0, 10.0)),
                         kw.pop("every", (3, 5)))
    base = dict(views=3, profile=prof, words=[], comments=[],
                caps=dict(feed.DEFAULT_CAPS), label="Тест", platform=None,
                allowed=story.ACTIONS)
    base.update(kw)
    return feed.FeedParams(**base)


def run(ctx, ui, params, seed=1):
    return feed.run_feed(ctx, ui, params, rng=random.Random(seed), clock=lambda: ctx.now)


def test_views_and_swipes():
    ctx = FakeCtx()
    ui = FakeUI(ctx)
    tally = run(ctx, ui, fp(views=4))
    assert ui.nexts == 4
    assert tally.counts["views"] == 4
    assert all(s >= 1 for s in ctx.sleeps)


def test_dwell_budget_includes_action_time():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=4.0)
    run(ctx, ui, fp(views=1, like=100))
    assert ui.performed == ["like"]
    assert ctx.sleeps == [6.0]            # 10 с на видео минус 4 с на лайк


def test_no_actions_means_full_dwell():
    ctx = FakeCtx()
    ui = FakeUI(ctx, actions=False)
    run(ctx, ui, fp(views=1, like=100))
    assert ui.performed == []
    assert ctx.sleeps == [10.0]


def test_action_order_is_fixed():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=1, like=100, favorite=100, follow=100, comment=100, comments=["класс"]))
    assert ui.performed == ["like", "favorite", "follow", "comment"]
    assert ui.texts[-1] == "класс"


def test_comment_skipped_without_phrases():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=1, comment=100, comments=[]))
    assert ui.performed == []


def test_allowed_filters_actions():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=1, like=100, follow=100, allowed=("like",)))
    assert ui.performed == ["like"]


def test_budget_taken_before_each_action_and_stops_run():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    params = fp(views=5, like=100, caps={**feed.DEFAULT_CAPS, "like": 2})
    with pytest.raises(BudgetReached):
        run(ctx, ui, params)
    assert ui.performed == ["like", "like"]        # третий лайк не состоялся
    assert ctx.limits["Тест: лайки"] == 2


def test_zero_cap_disables_action():
    ctx = FakeCtx()
    ui = FakeUI(ctx, action_cost=0)
    run(ctx, ui, fp(views=2, like=100, caps={**feed.DEFAULT_CAPS, "like": 0}))
    assert ui.performed == []
    assert ctx.budgets == {}


def test_search_rotation_not_on_first_video():
    ctx = FakeCtx()
    ui = FakeUI(ctx)
    tally = run(ctx, ui, fp(views=5, words=["alpha", "beta"], every=(2, 2)))
    assert len(ui.searched) == 2 and ui.searched[0] != ui.searched[1]
    assert tally.counts["searches"] == 2


def test_not_ready_triggers_recover_then_fails_if_still_not_ready():
    ctx = FakeCtx()
    ui = FakeUI(ctx, ready=False)
    with pytest.raises(StepFailed):
        run(ctx, ui, fp(views=2))
    assert ui.recovers == 1


def test_summary_logged_at_end():
    ctx = FakeCtx()
    run(ctx, FakeUI(ctx), fp(views=2))
    assert ctx.logs[-1].startswith("итог: просмотров 2")


def test_from_params_builds_and_validates():
    p = {"profile": "Тихий", "views": "12", "words": "a\nb\na", "comments": "x\n\ny",
         "like": "", "cap_like": "50", "cap_follow": 0}
    got = feed.from_params(p, label="TikTok", platform="tiktok")
    assert got.views == 12
    assert got.profile == story.PROFILES["quiet"]
    assert got.words == ["a", "b"] and got.comments == ["x", "y"]
    assert got.caps["like"] == 50 and got.caps["follow"] == 0 and got.caps["comment"] == 30


def test_from_params_zeroes_not_allowed_actions():
    got = feed.from_params({"profile": "Активный", "views": 5}, label="VK", allowed=("like",))
    assert got.profile.like == story.PROFILES["active"].like
    assert got.profile.comment == got.profile.follow == got.profile.favorite == 0


def test_from_params_reports_form_errors():
    with pytest.raises(ValueError) as e:
        feed.from_params({"profile": "Обычный", "views": 0}, label="x")
    assert "Сколько видео" in str(e.value)


def test_feed_params_shape():
    p = feed.feed_params(views=40)
    assert p["views"]["default"] == 40 and p["views"]["type"] == "number"
    assert p["profile"]["options"] == list(story.PROFILE_LABELS)
    assert p["words"]["type"] == "textarea"
    assert "cap_like" in p
    assert "comments" not in feed.feed_params(actions=False)
    assert "cap_like" not in feed.feed_params(actions=False)


def test_swipe_up_uses_fractions_and_goes_up():
    calls = []

    class C:
        def swipe(self, x1, y1, x2, y2, duration=0.25):
            calls.append((x1, y1, x2, y2, duration))

    feed.swipe_up(C(), random.Random(2))
    x1, y1, x2, y2, d = calls[0]
    assert 0.4 <= x1 <= 0.8 and 0.4 <= x2 <= 0.8
    assert 0.55 <= y1 <= 0.72 and 0.12 <= y2 <= 0.24 and y2 < y1
    assert 0.3 <= d <= 0.6
