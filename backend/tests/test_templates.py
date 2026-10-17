"""Готовые шаблоны прогрева: загрузка и человеческий сеанс на фейковом ctx."""
import importlib.util
import random
from pathlib import Path

import pytest

from farm import config, scenarios

WARMUPS = ("warmup_vk", "warmup_inst", "warmup_tiktok", "warmup_tg")
HUMAN = Path(config.SCENARIOS_DIR) / "_human.py"


def _human():
    spec = importlib.util.spec_from_file_location("test_human", HUMAN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cancelled(Exception):
    pass


class FakeCtx:
    """Пишет вызовы, время — только через sleep (фейковые часы)."""

    def __init__(self, installed=(), cancel_at=None):
        self.now = 0.0
        self.calls = []
        self.installed = list(installed)
        self.cancel_at = cancel_at
        self.size = (1080, 2400)
        self.d = None
        self.params = {}

    def clock(self):
        return self.now

    def check_cancel(self):
        if self.cancel_at is not None and self.now >= self.cancel_at:
            raise Cancelled("отменено")

    def sleep(self, s):
        assert s >= 0
        self.check_cancel()
        self.now += s

    def swipe(self, *a):
        self.calls.append(("swipe", a))
        self.now += a[-1]

    def tap(self, *a):
        self.calls.append(("tap", a))

    def back(self):
        self.calls.append(("back",))

    def log(self, msg):
        self.calls.append(("log", msg))

    def packages(self):
        return self.installed

    def fail(self, msg):
        raise AssertionError(msg)


def test_loader_marks_all_warmups_as_templates():
    found = {s.key: s for s in scenarios.discover(force=True)}
    for key in WARMUPS:
        sc = found[key]
        assert not sc.error, sc.error
        d = sc.to_dict()
        assert d["template"] is True
        assert sc.name.startswith("Прогрев")
        p = sc.params
        assert p["minutes"]["default"] == 10
        assert p["like_chance"]["default"] == 10 and p["like_chance"]["max"] == 30
        assert p["only_watch"]["type"] == "bool"
        resolved = scenarios.resolve_params(sc, {})
        assert resolved == {"minutes": 10, "like_chance": 10, "only_watch": False}
    assert found["smoke"].to_dict()["template"] is False
    assert "_human" not in found


@pytest.mark.parametrize("minutes", [1, 3, 10])
def test_session_respects_minutes(minutes):
    h = _human()
    ctx = FakeCtx()
    stats = h.feed_session(ctx, minutes, 0, rnd=random.Random(minutes), clock=ctx.clock)
    assert stats["swipes"] > 0
    assert 0.85 * minutes * 60 <= stats["seconds"] <= minutes * 60
    # последнее действие может чуть перехлестнуть бюджет, но не больше пары секунд
    assert ctx.now <= minutes * 60 + 3


def test_like_chance_clamped_and_only_watch():
    h = _human()
    assert h.clamp_chance(90) == 0.30
    assert h.clamp_chance(-5) == 0
    assert h.clamp_chance("abc") == 0

    likes = []

    def like(ctx):
        likes.append(ctx.now)
        return True

    ctx = FakeCtx()
    stats = h.feed_session(ctx, 60, 100, like=like, rnd=random.Random(1), clock=ctx.clock)
    ratio = stats["likes"] / stats["swipes"]
    assert 0.18 < ratio < 0.42, ratio   # 100 % в форме → не больше 30 %

    ctx = FakeCtx()
    likes.clear()
    stats = h.feed_session(ctx, 10, 30, only_watch="true", like=like,
                           rnd=random.Random(2), clock=ctx.clock)
    assert stats["likes"] == 0 and not likes


def test_failed_like_does_not_stop_session_but_cancel_does():
    h = _human()

    def broken(ctx):
        raise RuntimeError("нет кнопки")

    ctx = FakeCtx()
    h.feed_session(ctx, 2, 30, like=broken, rnd=random.Random(3), clock=ctx.clock)
    assert ctx.now >= 0.85 * 120

    ctx = FakeCtx(cancel_at=30)
    with pytest.raises(Cancelled):
        h.feed_session(ctx, 10, 0, rnd=random.Random(4), clock=ctx.clock)
    assert ctx.now < 40


def test_ensure_app_fallback_and_fail():
    h = _human()
    ctx = FakeCtx(installed=["com.ss.android.ugc.trill"])
    assert h.ensure_app(ctx, ["com.zhiliaoapp.musically", "com.ss.android.ugc.trill"],
                        "TikTok") == "com.ss.android.ugc.trill"
    with pytest.raises(AssertionError, match="VK не установлен на телефоне"):
        h.ensure_app(FakeCtx(), ["com.vkontakte.android"], "VK")
