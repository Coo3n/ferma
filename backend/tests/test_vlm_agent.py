"""ИИ-агент: проверка действий, разбор ответа, лимиты, исполнение, рецепт."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from farm import config
from farm.api import screen
from farm.api import vlm as api
from farm.vlm import agent

TAP = {"kind": "tap", "x": 0.5, "y": 0.5}
REPLY = '```json\n{"action": {"kind": "tap", "x": 0.4, "y": 0.6}, "why": "кнопка"}\n```'


@pytest.fixture
def ready(monkeypatch):
    cfg = SimpleNamespace(enabled=True, url="http://x", max_per_job=5, max_per_day=50)
    monkeypatch.setattr(agent.settings, "get", lambda: cfg)
    monkeypatch.setattr(agent.control, "screenshot", lambda serial, quality=85: b"img")
    monkeypatch.setattr(agent.loc, "screen_gate", lambda c, image: False)
    monkeypatch.setattr(agent.loc.safety, "secret_goal", lambda *t: False)
    monkeypatch.setattr(agent.control, "size", lambda serial: (1080, 2400))
    monkeypatch.setattr(agent.control, "dump_hierarchy", lambda serial: "<hierarchy/>")
    monkeypatch.setattr(agent.tree, "parse", lambda xml, w, h: [])
    monkeypatch.setattr(agent.loc.safety, "secret_screen", lambda nodes: False)
    calls = {"reserve": 0, "refund": 0, "max_tokens": None}

    def reserve(job, a, b):
        calls["reserve"] += 1
        return True, ""
    monkeypatch.setattr(agent.usage, "reserve", reserve)
    monkeypatch.setattr(agent.usage, "refund", lambda job: calls.__setitem__("refund", calls["refund"] + 1))

    def ask(image, prompt, cfg=None, max_tokens=300):
        calls["max_tokens"] = max_tokens
        calls["prompt"] = prompt
        return REPLY
    monkeypatch.setattr(agent.client, "ask", ask)
    return calls


# ---- validate_action

@pytest.mark.parametrize("action", [
    TAP,
    {"kind": "swipe", "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2},
    {"kind": "type", "value": "привет"},
    {"kind": "key", "name": "back"},
    {"kind": "launch_app", "package": "org.telegram.messenger"},
    {"kind": "open_url", "url": "https://example.com/a?b=1"},
    {"kind": "wait", "seconds": 3},
])
def test_valid_actions_pass(ready, action):
    assert agent.validate_action(action)["kind"] == action["kind"]


@pytest.mark.parametrize("action", [
    {"kind": "shell", "cmd": "reboot"},
    {"kind": "unlock"}, {"kind": "tap"}, {"kind": "tap", "x": "a", "y": 1},
    {"kind": "tap", "x": float("nan"), "y": 0}, {"kind": "tap", "x": True, "y": 0},
    {"kind": "key", "name": "power"}, {"kind": "key", "name": "KEYCODE_HOME; reboot"},
    {"kind": "launch_app", "package": "x; reboot"}, {"kind": "launch_app", "package": "nodots"},
    {"kind": "open_url", "url": "file:///etc/passwd"}, {"kind": "open_url", "url": "javascript:alert(1)"},
    {"kind": "open_url", "url": "http://a b"}, {"kind": "open_url", "url": "https://"},
    {"kind": "type", "value": ""}, {"kind": "type", "value": "x" * 501}, {"kind": "type", "value": 5},
    {"kind": "wait", "seconds": "abc"}, "tap", None, {},
])
def test_invalid_actions_rejected(ready, action):
    with pytest.raises(agent.AgentError):
        agent.validate_action(action)


def test_coordinates_clamped_and_wait_capped(ready):
    a = agent.validate_action({"kind": "tap", "x": 5, "y": -2})
    assert (a["x"], a["y"]) == (1.0, 0.0)
    assert agent.validate_action({"kind": "wait", "seconds": 999})["seconds"] == 10


def test_extra_fields_are_dropped(ready):
    a = agent.validate_action({"kind": "key", "name": "home", "cmd": "reboot"})
    assert a == {"kind": "key", "name": "home"}


def test_secret_in_type_refused(ready, monkeypatch):
    monkeypatch.setattr(agent.loc.safety, "secret_goal", lambda *t: True)
    with pytest.raises(agent.AgentError) as e:
        agent.validate_action({"kind": "type", "value": "мой пароль 123"})
    assert "пароли" in str(e.value)


# ---- parse_reply

def test_parse_fenced_action(ready):
    r = agent.parse_reply(REPLY)
    assert r["action"] == {"kind": "tap", "x": 0.4, "y": 0.6} and r["why"] == "кнопка"


def test_parse_done_and_ask(ready):
    assert agent.parse_reply('{"done": true, "why": "ok"}') == {"done": True, "why": "ok"}
    assert agent.parse_reply('текст {"ask": true, "why": "капча"} ещё')["ask"] is True


@pytest.mark.parametrize("text", ["", "нет json", '{"foo": 1}', "[1]", '{"action": {"kind": "tap"', "```json\n{```"])
def test_parse_unreadable(ready, text):
    with pytest.raises(agent.UnreadableReply):
        agent.parse_reply(text)


def test_parse_shell_action_is_error(ready):
    with pytest.raises(agent.AgentError):
        agent.parse_reply('{"action": {"kind": "shell", "cmd": "reboot"}, "why": ""}')


# ---- is_loop

def _h(action, result="ok"):
    return {"action": action, "why": "", "result": result}


def test_loop_after_three_identical(ready):
    assert not agent.is_loop([_h(TAP)], TAP)
    assert agent.is_loop([_h(TAP), _h(TAP)], TAP)
    assert not agent.is_loop([_h(TAP), _h({"kind": "key", "name": "back"})], TAP)
    assert not agent.is_loop([_h(TAP), _h(TAP)], {"kind": "key", "name": "back"})
    assert not agent.is_loop([], TAP)


def test_loop_ignores_skipped(ready):
    assert not agent.is_loop([_h(TAP), _h(TAP, "skipped")], TAP)


def test_step_reports_loop_as_ask(ready):
    out = agent.step("S1", "x", [_h({"kind": "tap", "x": 0.4, "y": 0.6})] * 2)
    assert out.get("ask") and out["why"]


# ---- step

def test_step_happy_path(ready):
    out = agent.step("S1", "открой Telegram", [])
    assert out["action"]["kind"] == "tap"
    assert ready["reserve"] == 1 and ready["refund"] == 0
    assert ready["max_tokens"] >= 600
    assert "открой Telegram" in ready["prompt"]


def test_step_prompt_has_history_without_shell(ready):
    agent.step("S1", "x", [_h(TAP)])
    assert "tap" in ready["prompt"] and "shell" not in ready["prompt"]


def test_step_off(ready, monkeypatch):
    monkeypatch.setattr(agent.settings, "get", lambda: SimpleNamespace(enabled=False, url="", max_per_job=1, max_per_day=1))
    with pytest.raises(agent.AgentError) as e:
        agent.step("S1", "x", [])
    assert "выключен" in str(e.value)


def test_step_secret_task(ready, monkeypatch):
    monkeypatch.setattr(agent.loc.safety, "secret_goal", lambda *t: True)
    with pytest.raises(agent.AgentError):
        agent.step("S1", "введи пароль", [])
    assert ready["reserve"] == 0


def test_step_secret_screen_and_secure_screen(ready, monkeypatch):
    monkeypatch.setattr(agent.tree, "parse", lambda xml, w, h: [object()])
    monkeypatch.setattr(agent.loc.safety, "secret_screen", lambda nodes: True)
    with pytest.raises(agent.AgentError):
        agent.step("S1", "x", [])
    monkeypatch.setattr(agent.loc.safety, "secret_screen", lambda nodes: False)
    monkeypatch.setattr(agent.loc, "screen_gate", lambda c, image: True)
    with pytest.raises(agent.AgentError):
        agent.step("S1", "x", [])
    assert ready["reserve"] == 0


def test_step_session_limit(ready, monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 3)
    with pytest.raises(agent.AgentError) as e:
        agent.step("S1", "x", [_h({"kind": "key", "name": "back"})] * 3)
    assert "3" in str(e.value) and ready["reserve"] == 0


def test_step_daily_limit(ready, monkeypatch):
    monkeypatch.setattr(agent.usage, "reserve", lambda job, a, b: (False, "лимит"))
    with pytest.raises(agent.AgentError):
        agent.step("S1", "x", [])


def test_step_refunds_on_failure_and_garbage(ready, monkeypatch):
    def boom(image, prompt, cfg=None, max_tokens=300):
        raise RuntimeError("нет связи")
    monkeypatch.setattr(agent.client, "ask", boom)
    with pytest.raises(agent.AgentError):
        agent.step("S1", "x", [])
    assert ready["refund"] == 1
    monkeypatch.setattr(agent.client, "ask", lambda *a, **k: "мусор")
    with pytest.raises(agent.UnreadableReply):
        agent.step("S1", "x", [])
    assert ready["refund"] == 2


def test_step_rejects_empty_task_and_bad_history(ready):
    with pytest.raises(agent.AgentError):
        agent.step("S1", "  ", [])
    with pytest.raises(agent.AgentError):
        agent.step("S1", "x", "не список")


# ---- do

@pytest.fixture
def phone(monkeypatch, ready):
    log = []
    for name in ("tap", "swipe", "text", "key", "launch", "url", "shell"):
        monkeypatch.setitem(screen.ACTIONS, name, (lambda n: lambda serial, p: log.append((n, serial, p)))(name))
    monkeypatch.setattr(agent.time, "sleep", lambda s: log.append(("sleep", s)))
    return log


def test_do_maps_actions(phone):
    for action, expected in [
        (TAP, ("tap", "S1", {"x": 0.5, "y": 0.5})),
        ({"kind": "type", "value": "hi"}, ("text", "S1", {"value": "hi"})),
        ({"kind": "key", "name": "back"}, ("key", "S1", {"name": "back"})),
        ({"kind": "launch_app", "package": "a.b"}, ("launch", "S1", {"package": "a.b"})),
        ({"kind": "open_url", "url": "https://a.b"}, ("url", "S1", {"url": "https://a.b"})),
    ]:
        phone.clear()
        assert agent.do("S1", action) == {"ok": True}
        assert phone == [expected]
    phone.clear()
    agent.do("S1", {"kind": "wait", "seconds": 50})
    assert phone == [("sleep", 10.0)]


def test_do_executes_only_valid(phone):
    for bad in ({"kind": "shell", "cmd": "reboot"}, {"kind": "key", "name": "power"},
                {"kind": "open_url", "url": "file:///x"}):
        with pytest.raises(agent.AgentError):
            agent.do("S1", bad)
    assert phone == []


def test_do_type_refused_on_password_screen(phone, monkeypatch):
    monkeypatch.setattr(agent.tree, "parse", lambda xml, w, h: [object()])
    monkeypatch.setattr(agent.loc.safety, "secret_screen", lambda nodes: True)
    with pytest.raises(agent.AgentError):
        agent.do("S1", {"kind": "type", "value": "hi"})
    assert phone == []


def test_do_phone_error_is_agent_error(phone, monkeypatch):
    def boom(serial, p):
        raise RuntimeError("офлайн")
    monkeypatch.setitem(screen.ACTIONS, "tap", boom)
    with pytest.raises(agent.AgentError):
        agent.do("S1", TAP)


# ---- recipe

def test_recipe_from_ok_steps_passes_normalize(ready):
    from farm.recorder import steps as schema
    hist = [_h({"kind": "launch_app", "package": "org.telegram.messenger"}),
            _h(TAP, "skipped"), _h({"kind": "wait", "seconds": 2}),
            _h({"kind": "swipe", "x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.2}),
            _h({"kind": "type", "value": "hi"}), _h({"kind": "key", "name": "back"}),
            _h({"kind": "open_url", "url": "https://a.b"}),
            _h(TAP, "ошибка телефона"), _h({"kind": "shell", "cmd": "x"})]
    r = agent.recipe("открой Telegram " + "я" * 60, hist)
    assert [s["kind"] for s in r["steps"]] == ["launch_app", "sleep", "swipe", "type", "key", "open_url"]
    assert r["key"].startswith("agent_") and r["meta"]["name"].startswith("Агент: ")
    assert len(r["meta"]["name"]) <= len("Агент: ") + 40
    schema.normalize_steps(r["steps"])
    schema.normalize_meta(r["meta"])


def test_recipe_empty_is_error(ready):
    with pytest.raises(agent.AgentError):
        agent.recipe("x", [_h(TAP, "skipped")])


# ---- API

def test_api_step_numbers_and_errors(ready, monkeypatch):
    monkeypatch.setattr(config, "AGENT_MAX_STEPS", 5)
    out = api.agent_step({"serial": "S1", "task": "x", "history": [_h(TAP, "skipped")]})
    assert out["step_no"] == 2 and out["left"] == 3 and out["action"]["kind"] == "tap"
    with pytest.raises(HTTPException) as e:
        api.agent_step({"serial": "S1", "task": "", "history": []})
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        api.agent_do({"serial": "S1", "action": {"kind": "shell", "cmd": "x"}})
    with pytest.raises(HTTPException):
        api.agent_recipe({"task": "x", "history": []})
