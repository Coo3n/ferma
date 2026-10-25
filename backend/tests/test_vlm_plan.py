"""Черновик сценария по описанию: разбор ответа модели, ограничения, рецепт."""
from types import SimpleNamespace

import pytest

from farm.vlm import plan

GOOD = """Вот шаги:
```json
[
  {"kind": "launch_app", "args": {"package": "org.telegram.messenger"}},
  {"kind": "sleep", "args": {"seconds": 2}},
  {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.3}},
  {"kind": "type", "args": {"value": "привет"}},
  {"kind": "key", "args": {"name": "back"}}
]
```"""


def test_parse_steps_from_fenced_json():
    steps = plan.parse_steps(GOOD)
    assert [s["kind"] for s in steps] == ["launch_app", "sleep", "swipe", "type", "key"]
    assert steps[0]["args"] == {"package": "org.telegram.messenger"}


def test_parse_steps_plain_array_without_fences():
    assert plan.parse_steps('[{"kind": "sleep", "args": {"seconds": 1}}]')[0]["kind"] == "sleep"


def test_parse_steps_drops_unknown_kinds_and_missing_args():
    text = ('[{"kind": "shell", "args": {"cmd": "rm -rf /"}},'
            ' {"kind": "swipe", "args": {"x1": 0.5}},'
            ' {"kind": "tap", "args": {"x": 0.5, "y": 0.5}},'
            ' "junk", 5, {"kind": "sleep", "args": {"seconds": "abc"}}]')
    steps = plan.parse_steps(text)
    assert [s["kind"] for s in steps] == ["tap"]


def test_parse_steps_never_lets_shell_through():
    with pytest.raises(plan.PlanError):
        plan.parse_steps('[{"kind": "shell", "args": {"cmd": "reboot"}}]')


def test_parse_steps_clamps_numbers_and_caps_count():
    many = ",".join('{"kind": "sleep", "args": {"seconds": 1}}' for _ in range(80))
    assert len(plan.parse_steps(f"[{many}]")) == plan.MAX_STEPS
    s = plan.parse_steps('[{"kind": "tap", "args": {"x": 5, "y": -2}}]')[0]["args"]
    assert 0 <= s["x"] <= 1 and 0 <= s["y"] <= 1
    sl = plan.parse_steps('[{"kind": "sleep", "args": {"seconds": 99999}}]')[0]["args"]
    assert sl["seconds"] <= plan.MAX_SLEEP


@pytest.mark.parametrize("text", ["", "no json here", "[]", '{"kind": "sleep"}', "[1, 2]"])
def test_parse_steps_empty_raises(text):
    with pytest.raises(plan.PlanError):
        plan.parse_steps(text)


def test_build_prompt_contains_task_and_allowed_kinds():
    p = plan.build_prompt("открой Telegram")
    assert "открой Telegram" in p
    for kind in plan.ALLOWED:
        assert kind in p
    assert "shell" not in p


def test_recipe_for_is_valid_for_recorder():
    from farm.recorder import steps as schema
    steps = plan.parse_steps(GOOD)
    recipe = plan.recipe_for("открой Telegram и пролистай ленту", steps)
    assert recipe["key"].startswith("chernovik_")
    assert recipe["meta"]["name"].startswith("Черновик:")
    schema.normalize_steps(recipe["steps"])              # не бросает


@pytest.fixture
def ready(monkeypatch):
    cfg = SimpleNamespace(enabled=True, url="http://x", max_per_job=5, max_per_day=50)
    monkeypatch.setattr(plan.settings, "get", lambda: cfg)
    monkeypatch.setattr(plan.control, "screenshot", lambda serial, quality=85: b"img")
    monkeypatch.setattr(plan.loc, "screen_gate", lambda c, image: False)
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: False)
    monkeypatch.setattr(plan.usage, "reserve", lambda job, a, b: (True, ""))
    monkeypatch.setattr(plan.usage, "refund", lambda job: None)
    monkeypatch.setattr(plan.client, "ask", lambda image, prompt, cfg=None: GOOD)
    return cfg


def test_plan_happy_path(ready):
    assert [s["kind"] for s in plan.plan("S1", "открой Telegram")][0] == "launch_app"


def test_plan_refuses_when_assistant_is_off(ready, monkeypatch):
    monkeypatch.setattr(plan.settings, "get", lambda: SimpleNamespace(enabled=False, url="", max_per_job=1, max_per_day=1))
    with pytest.raises(plan.PlanError) as e:
        plan.plan("S1", "x")
    assert "выключен" in str(e.value)


def test_plan_refuses_secret_goals_and_secure_screens(ready, monkeypatch):
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: True)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "введи пароль")
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: False)
    monkeypatch.setattr(plan.loc, "screen_gate", lambda c, image: True)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")


def test_plan_refuses_when_limit_reached(ready, monkeypatch):
    monkeypatch.setattr(plan.usage, "reserve", lambda job, a, b: (False, "лимит"))
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")


def test_plan_refunds_quota_when_model_fails(ready, monkeypatch):
    refunded = []
    monkeypatch.setattr(plan.usage, "refund", lambda job: refunded.append(job))

    def boom(image, prompt, cfg=None):
        raise RuntimeError("нет связи")
    monkeypatch.setattr(plan.client, "ask", boom)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")
    assert refunded


def test_plan_rejects_empty_task(ready):
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "   ")
