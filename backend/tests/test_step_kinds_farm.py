"""Шаги для ферм соцсетей: double_tap, wait, wait_gone, sleep «от–до», proxy."""
import ast
from datetime import date

import pytest

from farm import netproxy
from farm.context import DeviceContext, StepFailed
from farm.recorder import codegen, steps, validate

META = {"name": "Т", "description": "", "watch_popups": False, "human": False}
SWIPE = {"kind": "swipe", "args": {"x1": .5, "y1": .8, "x2": .5, "y2": .3}}


def _code(*raw):
    code = codegen.render(META, {}, steps.normalize_steps(list(raw)), today=date(2026, 1, 1))
    ast.parse(code)
    return code.split("def run(ctx):\n", 1)[1]


# ---------------------------------------------------------------- схема
def test_double_tap():
    st = steps.normalize_step({"kind": "double_tap", "args": {"x": 0.5, "y": "0.4"}})
    assert st["args"] == {"x": 0.5, "y": 0.4}
    with pytest.raises(steps.StepError, match="не хватает"):
        steps.normalize_step({"kind": "double_tap", "args": {"x": 0.5}})
    assert _code({"kind": "double_tap", "args": {"x": .5, "y": .5}}) == "    ctx.double_tap(0.5, 0.5)\n"


@pytest.mark.parametrize("kind", ["wait", "wait_gone"])
def test_wait_нормализация_и_код(kind):
    st = steps.normalize_step({"kind": kind, "any": ['text="Лента"']})
    assert st["args"] == {"timeout": 20, "on_fail": "fail"}
    fn = "wait_for" if kind == "wait" else "wait_for_gone"
    assert _code({"kind": kind, "any": ['text="Лента"']}) == \
        f'    ctx.{fn}([dict(text="Лента")], timeout=20)\n'
    assert _code({"kind": kind, "any": ['text="A"'], "args": {"timeout": 5, "on_fail": "skip"}}) == \
        f'    ctx.{fn}([dict(text="A")], timeout=5, on_fail="skip")\n'
    assert steps.label_of(st) in ("Ждать, пока появится: Лента", "Ждать, пока исчезнет: Лента")


@pytest.mark.parametrize("kind", ["wait", "wait_gone"])
def test_wait_ошибки(kind):
    with pytest.raises(steps.StepError, match="чего ждать"):
        steps.normalize_step({"kind": kind})
    for bad in (0, 301):
        with pytest.raises(steps.StepError, match="от 1 до 300"):
            steps.normalize_step({"kind": kind, "any": ['text="A"'], "args": {"timeout": bad}})
    with pytest.raises(steps.StepError, match="fail, skip или ask"):
        steps.normalize_step({"kind": kind, "any": ['text="A"'], "args": {"on_fail": "x"}})
    with pytest.raises(steps.StepError, match="управляющие|только пары"):
        steps.normalize_step({"kind": kind, "any": ['text="A")\nimport os']})


def test_sleep_диапазон():
    assert steps.normalize_step({"kind": "sleep", "args": {"seconds": 1}})["args"] == {"seconds": 1}
    st = steps.normalize_step({"kind": "sleep", "args": {"seconds": 1, "seconds_max": 4}})
    assert st["args"] == {"seconds": 1, "seconds_max": 4}
    assert _code({"kind": "sleep", "args": {"seconds": 1, "seconds_max": 4}}) == \
        "    ctx.sleep_between(1, 4)\n"
    assert _code({"kind": "sleep", "args": {"seconds": 2}}) == "    ctx.sleep(2)\n"
    with pytest.raises(steps.StepError, match="«до» не может быть меньше"):
        steps.normalize_step({"kind": "sleep", "args": {"seconds": 5, "seconds_max": 2}})
    with pytest.raises(steps.StepError, match="параметр"):
        steps.normalize_step({"kind": "sleep", "param": "p", "args": {"seconds": 1, "seconds_max": 2}})


def test_proxy():
    st = steps.normalize_step({"kind": "proxy", "args": {"account": "vk"}})
    assert st["args"] == {"account": "vk"}
    assert _code({"kind": "proxy", "args": {"account": "tg"}}) == '    ctx.use_proxy("tg")\n'
    assert _code({"kind": "proxy", "args": {"off": True}}) == "    ctx.proxy_off()\n"
    assert steps.label_of(steps.normalize_step({"kind": "proxy", "args": {"off": True}})) == "Снять прокси"
    for bad in ({}, {"account": "vk", "off": True}):
        with pytest.raises(steps.StepError, match="либо аккаунт"):
            steps.normalize_step({"kind": "proxy", "args": bad})
    with pytest.raises(steps.StepError, match="платформа"):
        steps.normalize_step({"kind": "proxy", "args": {"account": "fb"}})


def test_validate_и_line_map():
    raw = [{"kind": "sleep", "args": {"seconds": 5, "seconds_max": 90}},
           {"kind": "wait", "any": ['text="A"']}, SWIPE]
    res = validate.validate({"meta": META, "steps": raw})
    assert res["ok"] and "90" in res["warnings"][0]["text"]
    code, lm = codegen.render_mapped(META, {}, steps.normalize_steps(raw), today=date(2026, 1, 1))
    assert sorted(lm.values()) == [0, 1, 2]
    bad = validate.validate({"meta": META, "steps": [{"kind": "wait"}]})
    assert not bad["ok"] and bad["errors"][0]["step"] == 0


# ---------------------------------------------------------------- рантайм
class Fake(DeviceContext):
    """Контекст без телефона: перехватывает всё, что ходит наружу."""
    def __init__(self):
        self.serial = "s"
        self.human = False
        self.speed = 1
        self.log_lines, self.shells, self.slept = [], [], []
        self.visible = []        # очередь ответов _wait_features
        self.acc = {}
        self.recent_scroll = False
        self.last_tap = None

    def log(self, m): self.log_lines.append(m)
    def check_cancel(self): pass
    def _pre_action(self): pass
    def sleep(self, s): self.slept.append(s)
    def shell(self, cmd, timeout=30): self.shells.append(cmd)
    def account(self, platform=None):
        if self.acc is None:
            raise StepFailed("к телефону не привязан аккаунт")
        return self.acc
    def _wait_features(self, features, timeout):
        return self.visible.pop(0) if self.visible else self.visible_default
    visible_default = False


def test_sleep_between_границы():
    ctx = Fake()
    for _ in range(50):
        ctx.sleep_between(1, 4)
    assert all(1 <= s <= 4 for s in ctx.slept) and len(set(ctx.slept)) > 1


def test_double_tap_зовёт_control(monkeypatch):
    from farm import control
    calls = []
    monkeypatch.setattr(control, "double_tap", lambda *a: calls.append(a))
    ctx = Fake()
    ctx.double_tap(0.5, 0.5)
    assert calls == [("s", 0.5, 0.5)]
    ctx.human = True
    ctx.double_tap(0.5, 0.5)
    assert abs(calls[1][1] - 0.5) <= 0.008 and 0 <= calls[1][2] <= 1


def test_double_tap_запасной_путь(monkeypatch):
    from farm.control import input as inp
    shells = []
    monkeypatch.setattr(inp, "via_u2", lambda s, f: False)
    monkeypatch.setattr(inp, "to_pixels", lambda s, x, y: (10, 20))
    monkeypatch.setattr(inp.adb, "shell", lambda s, c, **k: shells.append(c))
    monkeypatch.setattr(inp.time, "sleep", lambda s: shells.append(("sleep", s)))
    inp.double_tap("s", .1, .2)
    assert shells == [["input", "tap", "10", "20"], ("sleep", 0.08), ["input", "tap", "10", "20"]]


def test_wait_for_нашёл_сразу():
    ctx = Fake()
    ctx.visible = [True]
    ctx.wait_for([dict(text="A")], timeout=5)


def test_wait_for_не_дождался():
    ctx = Fake()
    with pytest.raises(StepFailed, match="не дождался"):
        ctx.wait_for([dict(text="A")], timeout=0)
    ctx.wait_for([dict(text="A")], timeout=0, on_fail="skip")
    assert any("иду дальше" in m for m in ctx.log_lines)


def test_wait_for_gone():
    ctx = Fake()
    ctx.visible = [True, True, False]
    ctx.wait_for_gone([dict(text="A")], timeout=60)
    ctx.visible_default = True
    with pytest.raises(StepFailed, match="не исчезнет"):
        ctx.wait_for_gone([dict(text="A")], timeout=0)


def test_wait_for_ask(monkeypatch):
    from farm import context
    ctx = Fake()
    ctx._stuck = lambda беда, **k: context.HOLD_SKIP
    ctx.wait_for([dict(text="A")], timeout=0, on_fail="ask")


@pytest.mark.parametrize("raw,want", [
    ("10.0.0.1:8080", "10.0.0.1:8080"),
    ("http://proxy.example.com:3128", "proxy.example.com:3128"),
])
def test_proxy_разбор(raw, want):
    assert netproxy.system_proxy(raw) == want


@pytest.mark.parametrize("raw", ["user:SECRETPW@1.2.3.4:80", "1.2.3.4:80:user:SECRETPW",
                                 "socks5://u:SECRETPW@h:1", "http://u:SECRETPW@h:1"])
def test_proxy_с_логином_без_пароля_в_тексте(raw):
    with pytest.raises(netproxy.ProxyError) as e:
        netproxy.system_proxy(raw)
    assert "SECRETPW" not in str(e.value)


@pytest.mark.parametrize("raw", ["", None, "хост", "h:0", "h:99999", "h:abc", "socks5://h:1"])
def test_proxy_мусор(raw):
    with pytest.raises(netproxy.ProxyError):
        netproxy.system_proxy(raw)


def test_use_proxy_ставит_и_снимает():
    ctx = Fake()
    ctx.acc = {"proxy": "10.0.0.1:8080"}
    ctx.use_proxy("vk")
    ctx.proxy_off()
    assert ctx.shells == ["settings put global http_proxy 10.0.0.1:8080",
                          "settings put global http_proxy :0"]


def test_use_proxy_пароль_не_в_логах_и_ошибке():
    ctx = Fake()
    ctx.acc = {"proxy": "10.0.0.1:8080:bob:SECRETPW"}
    with pytest.raises(StepFailed) as e:
        ctx.use_proxy("vk")
    assert "без логина" in str(e.value) and "SECRETPW" not in str(e.value)
    assert not ctx.shells
    assert not any("SECRETPW" in m for m in ctx.log_lines)


def test_use_proxy_нет_аккаунта_или_прокси():
    ctx = Fake()
    ctx.acc = None
    with pytest.raises(StepFailed, match="не привязан"):
        ctx.use_proxy("vk")
    ctx.acc = {"proxy": ""}
    with pytest.raises(StepFailed, match="не задан прокси"):
        ctx.use_proxy("vk")
