"""Описание формата рецепта для внешних помощников совпадает со схемой."""
from farm.recorder import steps
from farm.api import recorder as api_recorder


def test_схема_отдаёт_все_виды_шагов_и_блоки():
    data = api_recorder.recipe_schema()
    assert set(data["kinds"]) == set(steps.ARGS)
    assert data["blocks"] == ["chance", "loop", "until"]
    assert data["kinds"]["until"]["required"] == ["span"]
    assert data["limits"]["block_depth"] == steps.BLOCK_DEPTH_MAX


def test_пример_из_документации_проходит_проверку():
    items = steps.normalize_steps([
        {"kind": "launch_app", "args": {"package": "com.vkontakte.android"}},
        {"kind": "loop", "args": {"span": 3, "minutes": 10, "pause_min": 1, "pause_max": 3}},
        {"kind": "swipe", "args": {"x1": .5, "y1": .8, "x2": .5, "y2": .3}},
        {"kind": "chance", "args": {"span": 1, "percent": 15}},
        {"kind": "click", "selector": {"call": "click", "args": 'description="Нравится"',
                                       "fallbacks": ['resourceIdMatches=".*/like_button$"']}},
        {"kind": "until", "args": {"span": 1, "tries": 5, "on_fail": "ask"},
         "any": ['text="Подписаться"']},
        {"kind": "swipe", "args": {"x1": .5, "y1": .8, "x2": .5, "y2": .3}},
    ])
    assert [s["kind"] for s in items][:2] == ["launch_app", "loop"]
