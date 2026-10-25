"""Логика сюжетов: профили, проверка формы, слова, действия, сводка."""
import random

import pytest

from farm import story


def test_profile_by_label_and_key():
    assert story.resolve_profile("Тихий") == story.PROFILES["quiet"]
    assert story.resolve_profile("active") == story.PROFILES["active"]


def test_unknown_profile_falls_back_to_normal():
    assert story.resolve_profile("что-то") == story.PROFILES["normal"]
    assert story.resolve_profile(None) == story.PROFILES["normal"]


def test_overrides_win_over_profile():
    p = story.resolve_profile("Обычный", {"like": "55", "dwell_lo": 3, "dwell_hi": "9"})
    assert p.like == 55.0
    assert p.dwell == (3.0, 9.0)
    assert p.comment == story.PROFILES["normal"].comment


def test_empty_and_garbage_overrides_ignored():
    p = story.resolve_profile("Обычный", {"like": "", "comment": None, "follow": "abc", "favorite": True})
    assert p == story.PROFILES["normal"]


def test_override_lo_above_default_hi_pushes_hi_up():
    p = story.resolve_profile("Обычный", {"dwell_lo": 60})
    assert p.dwell[0] == 60.0 and p.dwell[1] >= 60.0


def test_validate_ok_for_defaults():
    assert story.validate({"profile": "Обычный", "views": 30}) == []


def test_validate_pause_order():
    errs = story.validate({"dwell_lo": 10, "dwell_hi": 5})
    assert any("Пауза" in e for e in errs)


def test_validate_rate_range_and_garbage():
    errs = story.validate({"like": 120, "comment": "много"})
    assert len(errs) == 2


def test_validate_views_range():
    assert story.validate({"views": 0})
    assert story.validate({"views": 5000})
    assert story.validate({"views": "12"}) == []


def test_validate_all_zero_rates_only_when_actions_needed():
    zero = {"profile": "Обычный", "like": 0, "comment": 0, "favorite": 0, "follow": 0}
    assert story.validate(zero)
    assert story.validate(zero, need_actions=False) == []


def test_validate_counts_only_allowed_actions():
    # лайк выключен, остальные включены, но разрешён только лайк — делать нечего
    params = {"profile": "Обычный", "like": 0}
    assert story.validate(params, allowed=("like",))
    assert story.validate(params) == []


def test_parse_lines_trims_dedups_and_limits():
    text = "  кошки \n\nсобаки\nкошки\r\n  \nптицы\nрыбы"
    assert story.parse_lines(text) == ["кошки", "собаки", "птицы", "рыбы"]
    assert story.parse_lines(text, limit=2) == ["кошки", "собаки"]
    assert story.parse_lines(None) == []
    assert story.parse_lines(123) == ["123"]


def test_word_rotator_changes_after_interval_and_never_repeats_twice():
    rot = story.WordRotator(["a", "b", "c"], every=(2, 2), rng=random.Random(1))
    got = [rot.tick() for _ in range(8)]
    assert got == [None, got[1], None, got[3], None, got[5], None, got[7]]
    words = [w for w in got if w]
    assert len(words) == 4
    assert all(x != y for x, y in zip(words, words[1:]))
    assert set(words) <= {"a", "b", "c"}


def test_word_rotator_single_word_and_empty():
    one = story.WordRotator(["x"], every=(1, 1), rng=random.Random(0))
    assert [one.tick() for _ in range(3)] == ["x", "x", "x"]
    empty = story.WordRotator([], every=(1, 1))
    assert [empty.tick() for _ in range(3)] == [None, None, None]


def test_pick_actions_all_or_nothing_at_extremes():
    full = story.Profile(100, 100, 100, 100, (5, 5), (3, 3))
    none = story.Profile(0, 0, 0, 0, (5, 5), (3, 3))
    assert story.pick_actions(full, random.Random(1)) == list(story.ACTIONS)
    assert story.pick_actions(none, random.Random(1)) == []


def test_pick_actions_respects_allowed_and_order():
    full = story.Profile(100, 100, 100, 100, (5, 5), (3, 3))
    assert story.pick_actions(full, random.Random(1), allowed=("like",)) == ["like"]
    assert story.pick_actions(full, random.Random(1), allowed=("comment", "like")) == ["like", "comment"]


def test_pick_actions_rate_is_roughly_right():
    p = story.Profile(30, 0, 0, 0, (5, 5), (3, 3))
    rng = random.Random(7)
    hits = sum("like" in story.pick_actions(p, rng) for _ in range(2000))
    assert 500 < hits < 700


def test_dwell_left():
    assert story.dwell_left(10, 4) == 6
    assert story.dwell_left(10, 12) == 1.0


def test_seek_plan_sums_exactly_and_respects_bounds():
    rng = random.Random(5)
    for total in (1, 7, 30, 61):
        plan = story.seek_plan(total, 3, 8, rng)
        assert sum(plan) == total
        assert all(1 <= s <= 8 for s in plan)
        assert all(s >= 3 for s in plan[:-1])   # короче lo может быть только последний шаг


def test_seek_plan_zero_total():
    assert story.seek_plan(0, 3, 8) == []


def test_tally_line():
    t = story.Tally()
    t.add("views", 14)
    t.add("like", 3)
    t.add("like")
    assert t.counts["like"] == 4
    assert t.line() == "просмотров 14, лайков 4"


def test_tally_line_empty():
    assert story.Tally().line() == "просмотров 0"


def test_tally_rejects_unknown_key():
    with pytest.raises(KeyError):
        story.Tally().add("fly")
