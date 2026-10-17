"""Устойчивость ctx: стабильность экрана, стражи, многослойные цели, якоря.
Устройство не нужно: поиск элементов и жесты подменяются."""
import json

import pytest

from farm import config, control, resolve
from farm.context import DeviceContext, StepFailed


class ФейкЭлемент:
    def __init__(self):
        self.clicked = 0

    def click(self):
        self.clicked += 1


def ctx_():
    return DeviceContext("test-serial", logger=lambda m: None)


def test_settle_зовёт_wait_stable(monkeypatch):
    ctx = ctx_()
    calls = []
    monkeypatch.setattr(control, "wait_stable", lambda serial: calls.append(serial))
    monkeypatch.setattr(config, "SETTLE", True)
    ctx._settle()
    assert calls == ["test-serial"]


def test_флаг_сценария_выключает_settle(monkeypatch):
    ctx = ctx_()
    calls = []
    monkeypatch.setattr(control, "wait_stable", lambda serial: calls.append(serial))
    monkeypatch.setattr(config, "SETTLE", True)
    ctx.settle = False
    ctx._settle()
    assert calls == []


def test_глобальный_выключатель_отключает_settle(monkeypatch):
    ctx = ctx_()
    calls = []
    monkeypatch.setattr(control, "wait_stable", lambda serial: calls.append(serial))
    monkeypatch.setattr(config, "SETTLE", False)
    ctx._settle()
    assert calls == []


def test_click_ждёт_стабильности_до_поиска(monkeypatch):
    ctx = ctx_()
    order = []
    monkeypatch.setattr(ctx, "_settle", lambda: order.append("settle"))
    el = ФейкЭлемент()
    monkeypatch.setattr(ctx, "find",
                        lambda timeout=10, **sel: order.append("find") or el)
    ctx.click(text="Войти")
    assert order == ["settle", "find"]
    assert el.clicked == 1


class МолчащиеСтражи:
    def try_all(self, ctx):
        return []


class СпасающиеСтражи:
    """Изображает стража, закрывшего попап: после вызова цель находится."""

    def __init__(self, state):
        self.state = state

    def try_all(self, ctx):
        self.state["rescued"] = True
        return ["фейковый-страж"]


def test_страж_спасает_промахнувшийся_click(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "_scroll_to", lambda **sel: None)
    el, state = ФейкЭлемент(), {"rescued": False}
    monkeypatch.setattr(ctx, "find",
                        lambda timeout=10, **sel: el if state["rescued"] else None)
    ctx._guards = СпасающиеСтражи(state)
    ctx.click(timeout=0.1, text="Далее")
    assert el.clicked == 1


def test_молчащие_стражи_не_мешают_падению(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "_scroll_to", lambda **sel: None)
    monkeypatch.setattr(ctx, "find", lambda timeout=10, **sel: None)
    ctx._guards = МолчащиеСтражи()
    with pytest.raises(StepFailed):
        ctx.click(timeout=0.1, text="Далее")


def test_упавшие_стражи_не_роняют_сценарий():
    ctx = ctx_()

    class Бомба:
        def try_all(self, c):
            raise RuntimeError("стражи сломались")

    ctx._guards = Бомба()
    assert ctx._rescue() is False


def test_click_target_тапает_найденную_точку(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    taps = []
    monkeypatch.setattr(ctx, "tap", lambda x, y: taps.append((x, y)))
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "ocr", "Войти"))
    ctx.click_target(text=["Войти"])
    assert taps == [(0.5, 0.6)]


def test_запасной_слой_попадает_в_журнал(monkeypatch):
    lines = []
    ctx = DeviceContext("s", logger=lines.append)
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "tap", lambda x, y: None)
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "ocr", "Войти"))
    ctx.click_target(text=["Войти"])
    assert any("ocr" in line for line in lines)


def test_слой_селекторов_журнал_не_засоряет(monkeypatch):
    lines = []
    ctx = DeviceContext("s", logger=lines.append)
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "tap", lambda x, y: None)
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "selector", ""))
    ctx.click_target(sel=[dict(text="Войти")])
    assert lines == []


def test_click_target_зовёт_стражей_и_падает(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(resolve, "resolve", lambda c, **kw: None)
    ctx._guards = МолчащиеСтражи()
    with pytest.raises(StepFailed):
        ctx.click_target(sel=[dict(text="x")], timeout=0.1)


def test_ассет_отдаёт_байты_и_масштаб(monkeypatch, tmp_path):
    assets = tmp_path / "demo_assets"
    assets.mkdir()
    png_bytes = "png-байты".encode("utf-8")
    (assets / "07_login.png").write_bytes(png_bytes)
    (assets / "meta.json").write_text(json.dumps({"screen_width": 500}), "utf-8")
    # size — property, поэтому подменяется на классе, а не на экземпляре
    monkeypatch.setattr(DeviceContext, "size", property(lambda self: (1000, 2000)))
    ctx = DeviceContext("s", logger=lambda m: None, scenario_assets=assets)
    assert ctx.asset("07_login.png") == (png_bytes, 2.0)
    assert ctx.asset("нет.png") == (None, 1.0)


def test_без_папки_ассетов_масштаб_единица():
    ctx = DeviceContext("s", logger=lambda m: None)
    assert ctx.asset("07_login.png") == (None, 1.0)


def test_якорь_проходит_по_признаку(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "exists",
                        lambda timeout=0.5, **sel: sel == {"text": "Вход"})
    ctx.expect_screen("login", any=[dict(resourceId="нет"), dict(text="Вход")],
                      timeout=0.5)   # не бросил исключение — значит, прошло


def test_якорь_спасается_стражем(monkeypatch):
    ctx = ctx_()
    state = {"rescued": False}
    monkeypatch.setattr(ctx, "exists", lambda timeout=0.5, **sel: state["rescued"])
    ctx._guards = СпасающиеСтражи(state)
    ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0.1)


def test_якорь_падает_с_описанием_чужого_экрана(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "exists", lambda timeout=0.5, **sel: False)
    monkeypatch.setattr(ctx, "current_app", lambda: "com.app.main")
    monkeypatch.setattr(ctx, "_screen_texts", lambda limit=5: ["Продолжить", "Пропустить"])
    monkeypatch.setattr(ctx, "_expect_artifacts", lambda name: None)
    # общий выход проверяется в test_detours.py; здесь он ходил бы к adb
    monkeypatch.setattr(config, "ESCAPE", False)
    ctx._guards = МолчащиеСтражи()
    with pytest.raises(StepFailed) as err:
        ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0.1)
    message = str(err.value)
    assert "login" in message
    assert "com.app.main" in message
    assert "Продолжить" in message


def test_якорь_без_признаков_отвергается():
    with pytest.raises(ValueError):
        ctx_().expect_screen("login", any=[])
