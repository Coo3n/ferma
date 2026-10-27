"""Черновик сценария по описанию: разбор ответа модели, ограничения, рецепт."""
from types import SimpleNamespace

import pytest

from farm.vlm import plan

GOOD = """Вот шаги:
```json
[
  {"kind": "launch_app", "args": {"package": "org.telegram.messenger"}},
  {"kind": "sleep", "args": {"seconds": 2}},
  {"kind": "swipe", "args": {"x1": 500, "y1": 800, "x2": 500, "y2": 300}},
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
            ' {"kind": "swipe", "args": {"x1": 500}},'
            ' {"kind": "tap", "args": {"x": 500, "y": 500}},'
            ' "junk", 5, {"kind": "sleep", "args": {"seconds": "abc"}}]')
    steps = plan.parse_steps(text)
    assert [s["kind"] for s in steps] == ["tap"]


def test_parse_steps_single_object_without_array():
    steps = plan.parse_steps('{"kind": "swipe", "args": {"x1": 500, "y1": 583, "x2": 500, "y2": 338}}')
    assert [s["kind"] for s in steps] == ["swipe"] and steps[0]["args"]["y1"] == 0.583


def test_parse_steps_drops_looping_repeats():
    same = '{"kind": "swipe", "args": {"x1": 500, "y1": 600, "x2": 500, "y2": 300}}'
    other = '{"kind": "key", "args": {"name": "back"}}'
    steps = plan.parse_steps(f"[{same},{same},{same},{same},{other},{same}]")
    assert [s["kind"] for s in steps] == ["swipe", "swipe", "key", "swipe"]


def test_parse_steps_never_lets_shell_through():
    with pytest.raises(plan.PlanError):
        plan.parse_steps('[{"kind": "shell", "args": {"cmd": "reboot"}}]')


def test_parse_steps_clamps_numbers_and_caps_count():
    many = ",".join('{"kind": "sleep", "args": {"seconds": %d}}' % (i + 1) for i in range(80))
    assert len(plan.parse_steps(f"[{many}]")) == plan.MAX_STEPS
    s = plan.parse_steps('[{"kind": "tap", "args": {"x": 250, "y": 750}}]')[0]["args"]
    assert (s["x"], s["y"]) == (0.25, 0.75)
    with pytest.raises(plan.PlanError):      # вне шкалы 0..1000 — шаг отброшен, а не прижат к углу
        plan.parse_steps('[{"kind": "tap", "args": {"x": 617000, "y": -2}}]')
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
    cfg = SimpleNamespace(enabled=True, url="http://x", model="m", max_per_job=5, max_per_day=50)
    monkeypatch.setattr(plan.settings, "get", lambda: cfg)
    monkeypatch.setattr(plan.control, "screenshot", lambda serial, quality=85: b"img")
    monkeypatch.setattr(plan.loc, "screen_gate", lambda c, image: False)
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: False)
    monkeypatch.setattr(plan.control, "size", lambda serial: (1080, 2400))
    monkeypatch.setattr(plan.control, "dump_hierarchy", lambda serial: "<hierarchy/>")
    monkeypatch.setattr(plan.tree, "parse", lambda xml, w, h: [])
    monkeypatch.setattr(plan.loc.safety, "secret_screen", lambda nodes: False)
    monkeypatch.setattr(plan.usage, "reserve", lambda job, a, b: (True, ""))
    monkeypatch.setattr(plan.usage, "refund", lambda job: None)
    monkeypatch.setattr(plan.client, "ask", lambda image, prompt, cfg=None, max_tokens=300: GOOD)
    return cfg


def test_plan_happy_path(ready):
    assert [s["kind"] for s in plan.plan("S1", "открой Telegram")][0] == "launch_app"


def test_plan_refuses_when_assistant_is_off(ready, monkeypatch):
    monkeypatch.setattr(plan.settings, "get", lambda: SimpleNamespace(enabled=False, url="", model="m", max_per_job=1, max_per_day=1))
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

    def boom(image, prompt, cfg=None, max_tokens=300):
        raise RuntimeError("нет связи")
    monkeypatch.setattr(plan.client, "ask", boom)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")
    assert refunded


def test_plan_rejects_empty_task(ready):
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "   ")


def test_five_plans_pass_quota_with_real_usage(ready, monkeypatch, tmp_path):
    from farm import config
    from farm.vlm import usage
    monkeypatch.setattr(plan.usage, "reserve", usage.reserve)       # настоящий reserve
    monkeypatch.setattr(plan.usage, "refund", usage.refund)
    monkeypatch.setattr(config, "VLM_USAGE_FILE", tmp_path / "vlm_usage.json")
    usage.reset_jobs()
    ready.max_per_job = 3
    ready.max_per_day = 200
    for _ in range(5):
        assert plan.plan("S1", "открой Telegram")
    usage.reset_jobs()


def test_plan_asks_with_big_token_budget(ready, monkeypatch):
    seen = {}

    def ask(image, prompt, cfg=None, max_tokens=300):
        seen["t"] = max_tokens
        return GOOD
    monkeypatch.setattr(plan.client, "ask", ask)
    plan.plan("S1", "x")
    assert seen["t"] == 1800


def test_client_ask_sends_max_tokens(monkeypatch):
    import json as _json
    from types import SimpleNamespace as NS
    from farm.vlm import client
    sent = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_open(req, timeout=None):
        sent["body"] = _json.loads(req.data)
        return Resp()
    monkeypatch.setattr(client.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(client, "shrink", lambda b, w: b)
    cfg = NS(url="http://x/v1", model="m", key="", max_width=100, timeout=5)
    client.ask(b"i", "p", cfg)
    assert sent["body"]["max_tokens"] == 300
    client.ask(b"i", "p", cfg, max_tokens=1800)
    assert sent["body"]["max_tokens"] == 1800


def test_plan_refunds_when_reply_truncated(ready, monkeypatch):
    refunded = []
    monkeypatch.setattr(plan.usage, "refund", lambda job: refunded.append(job))
    monkeypatch.setattr(plan.client, "ask", lambda *a, **k: '[{"kind": "sleep", "args": {"sec')
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")
    assert refunded


def test_plan_no_refund_when_reply_readable_but_empty(ready, monkeypatch):
    refunded = []
    monkeypatch.setattr(plan.usage, "refund", lambda job: refunded.append(job))
    monkeypatch.setattr(plan.client, "ask", lambda *a, **k: '[{"kind": "shell", "args": {}}]')
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")
    assert not refunded


def test_plan_refuses_secret_screen(ready, monkeypatch):
    monkeypatch.setattr(plan.tree, "parse", lambda xml, w, h: ["node"])
    monkeypatch.setattr(plan.loc.safety, "secret_screen", lambda nodes: True)
    asked = []
    monkeypatch.setattr(plan.client, "ask", lambda *a, **k: asked.append(1) or GOOD)
    with pytest.raises(plan.PlanError) as e:
        plan.plan("S1", "x")
    assert "пароля" in str(e.value) and not asked


def test_plan_wraps_screenshot_and_dump_failures(ready, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("device offline")
    monkeypatch.setattr(plan.control, "screenshot", boom)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")
    monkeypatch.setattr(plan.control, "screenshot", lambda serial, quality=85: b"img")
    monkeypatch.setattr(plan.control, "dump_hierarchy", boom)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")


def test_autoglm_черновик_целиком_не_составляет(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(plan.settings, "get", lambda: SimpleNamespace(
        enabled=True, url="http://x", model="AutoGLM-Phone-9B"))
    with pytest.raises(plan.PlanError, match="по одному шагу"):
        plan.plan("S1", "открой настройки")
