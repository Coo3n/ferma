"""Блоки конструктора: «с шансом», «пока не найдёшь», вложенность — код, ctx, запуск с шага."""
import types
from datetime import date

import pytest

from farm import stepflow
from farm.context import DeviceContext, StepFailed
from farm.recorder import codegen, steps

META = {"name": "Т", "description": "", "watch_popups": False, "human": False}
LIKE = {"kind": "click", "selector": {"call": "click", "args": 'description="Нравится"'}}
SWIPE = {"kind": "swipe", "args": {"x1": .5, "y1": .8, "x2": .5, "y2": .3}}


def _лента():
    """Листать 10 минут и иногда лайкать; потом искать «Подписаться» свайпами."""
    return steps.normalize_steps([
        {"kind": "loop", "args": {"span": 3, "minutes": 10}},
        SWIPE,
        {"kind": "chance", "args": {"span": 1, "percent": 15}},
        LIKE,
        {"kind": "until", "args": {"span": 1, "tries": 5, "on_fail": "ask"},
         "any": ['text="Подписаться"']},
        SWIPE,
        {"kind": "key", "args": {"name": "home"}},
    ])


def test_шанс_и_поиск_валидируются():
    with pytest.raises(steps.StepError, match="от 1 до 100"):
        steps.normalize_steps([{"kind": "chance", "args": {"span": 1, "percent": 0}}, SWIPE])
    with pytest.raises(steps.StepError, match="что искать"):
        steps.normalize_steps([{"kind": "until", "args": {"span": 1}}, SWIPE])
    with pytest.raises(steps.StepError, match="skip, fail или ask"):
        steps.normalize_steps([{"kind": "until", "args": {"span": 1, "on_fail": "x"},
                                "any": ['text="A"']}, SWIPE])
    st = steps.normalize_steps([{"kind": "until", "args": {"span": 1}, "any": ['text="A"']}, SWIPE])[0]
    assert st["args"] == {"span": 1, "tries": 20, "on_fail": "skip"}
    assert steps.label_of(st) == "Пока не найдёшь: A"


def test_код_вложенных_блоков():
    code, lm = codegen.render_mapped(META, {}, _лента(), today=date(2026, 1, 1))
    compile(code, "s.py", "exec")
    body = code.split("def run(ctx):\n", 1)[1]
    assert body == (
        "    for _ in ctx.loop(minutes=10):\n"
        "        ctx.swipe(0.5, 0.8, 0.5, 0.3, 0.25)\n"
        "        if ctx.chance(15):\n"
        "            ctx.click(description=\"Нравится\")\n"
        "    for _ in ctx.until_found([dict(text=\"Подписаться\")], tries=5, on_fail=\"ask\"):\n"
        "        ctx.swipe(0.5, 0.8, 0.5, 0.3, 0.25)\n"
        "    ctx.key(\"home\")\n")
    assert sorted(lm.values()) == list(range(7))


# ------------------------------------------------------------------ ctx

def _ctx(monkeypatch, **kw):
    ctx = DeviceContext("s", logger=lambda m: None, **kw)
    monkeypatch.setattr(ctx, "sleep", lambda s: None)
    return ctx


def test_chance(monkeypatch):
    ctx = _ctx(monkeypatch)
    monkeypatch.setattr("farm.context.random.random", lambda: 0.10)
    assert ctx.chance(15) is True and ctx.chance(5) is False


def test_until_found_крутит_пока_нет_цели(monkeypatch):
    ctx = _ctx(monkeypatch)
    видно = iter([False, False, True])
    monkeypatch.setattr(ctx, "_wait_features", lambda f, t: next(видно))
    assert list(ctx.until_found([{"text": "A"}], tries=10)) == [0, 1]


def test_until_found_не_нашёл_skip_и_fail(monkeypatch):
    ctx = _ctx(monkeypatch)
    monkeypatch.setattr(ctx, "_wait_features", lambda f, t: False)
    assert list(ctx.until_found([{"text": "A"}], tries=3)) == [0, 1, 2]
    with pytest.raises(StepFailed, match="не нашёл «A» за 3"):
        list(ctx.until_found([{"text": "A"}], tries=3, on_fail="fail"))


def test_until_found_спрашивает_человека_и_даёт_ещё_круг(monkeypatch):
    ответы = iter(["retry", "skip"])
    ctx = _ctx(monkeypatch, hold=lambda что, **kw: next(ответы))
    monkeypatch.setattr("farm.context.config.HOLD", True)
    monkeypatch.setattr(ctx, "_wait_features", lambda f, t: False)
    assert list(ctx.until_found([{"text": "A"}], tries=2, on_fail="ask")) == [0, 1, 0, 1]


# ------------------------------------------------------------------ запуск с шага

class Rec:
    def __init__(self, lucky=True):
        self.calls = []
        self.lucky = lucky

    def swipe(self, *a):
        self.calls.append("swipe")

    def click(self, **kw):
        self.calls.append("like")

    def key(self, name):
        self.calls.append(name)

    def loop(self, **kw):
        return range(3)

    def chance(self, p):
        return self.lucky

    def until_found(self, features, tries=20, on_fail="skip"):
        return range(2)


def _module(tmp_path):
    code, lm = codegen.render_mapped(META, {}, _лента(), today=date(2026, 1, 1))
    path = tmp_path / "s.py"
    path.write_text(code, "utf-8")
    mod = types.ModuleType("s_mod")
    exec(compile(code, str(path), "exec"), mod.__dict__)
    return types.SimpleNamespace(path=str(path), module=mod), lm


def test_весь_сценарий(tmp_path):
    sc, _ = _module(tmp_path)
    rec = Rec(lucky=False)
    sc.module.run(rec)
    assert rec.calls == ["swipe"] * 3 + ["swipe"] * 2 + ["home"]


def test_проверка_шага_внутри_шанса_без_условия(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec(lucky=False)
    stepflow.module_from_step(sc, lm, 3, 4).run(rec)
    assert rec.calls == ["like"]


def test_проверка_заголовка_шанса_один_проход(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec(lucky=False)
    stepflow.module_from_step(sc, lm, 2, 3).run(rec)
    assert rec.calls == ["like"]


def test_запуск_с_середины_повтора_с_вложенным_шансом(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec(lucky=True)
    stepflow.module_from_step(sc, lm, 2).run(rec)
    # шанс внутри повтора — один раз (тело повтора порезано), дальше как есть
    assert rec.calls == ["like", "swipe", "swipe", "home"]


# ---------------------------------------------------------------- логика

def test_если_на_экране_и_выход_из_повтора_собираются_в_код():
    from farm.recorder import codegen, steps as st
    шаги = st.normalize_steps([
        {"kind": "loop", "args": {"span": 3, "times": 5}},
        {"kind": "if_seen", "args": {"span": 1, "negate": True}, "any": ['text="Лента"']},
        {"kind": "break"},
        {"kind": "swipe", "args": {"x1": .5, "y1": .8, "x2": .5, "y2": .3}},
        {"kind": "call", "args": {"scenario": "vk_login"}},
        {"kind": "finish", "args": {"result": "fail", "reason": "бан"}},
    ])
    src = codegen.render({"name": "t"}, {}, шаги)
    compile(src, "t", "exec")
    assert 'if not ctx.seen([dict(text="Лента")], timeout=3):' in src
    assert "            break" in src
    assert 'ctx.run("vk_login")' in src
    assert 'ctx.fail("бан")' in src


def test_выход_из_повтора_вне_повтора_отвергается():
    import pytest
    from farm.recorder import steps as st
    with pytest.raises(st.StepError):
        st.normalize_steps([{"kind": "chance", "args": {"span": 1, "percent": 50}},
                            {"kind": "break"}])


def test_проверка_шага_внутри_повтора_с_выходом_компилируется(tmp_path):
    import ast
    from farm import stepflow
    tree = ast.parse("def run(ctx):\n    for _ in ctx.loop(times=2):\n        break\n")
    fn = tree.body[0]
    fn.body = [stepflow._LooseBreak().visit(st) for st in fn.body[0].body]
    compile(ast.fix_missing_locations(tree), "t", "exec")
