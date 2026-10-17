"""Повтор по кругу в конструкторе: схема шага, код, ctx.loop, запуск с шага, журнал."""
import types
from datetime import date

import pytest

from farm import config, stepflow
from farm.context import DeviceContext
from farm.devices import runner as runner_mod
from farm.recorder import codegen, steps

META = {"name": "Т", "description": "", "watch_popups": False, "human": False}


def _loop(span=2, **kw):
    args = {"span": span, **({"times": 3} if not kw else kw)}
    return {"kind": "loop", "args": args}


def _сценарий():
    return steps.normalize_steps([
        {"kind": "key", "args": {"name": "home"}},
        _loop(2, times=3, pause_min=1, pause_max=2, watch=True),
        {"kind": "swipe", "args": {"x1": .5, "y1": .8, "x2": .5, "y2": .3}},
        {"kind": "key", "args": {"name": "back"}},
        {"kind": "sleep", "args": {"seconds": 1}},
    ])


# ------------------------------------------------------------------ схема

def test_повтор_нормализуется_с_целыми_числами():
    st = steps.normalize_steps([_loop(1, times=5.0), {"kind": "unlock", "args": {}}])[0]
    assert st["args"] == {"span": 1, "times": 5}
    assert steps.label_of(st) == "Повтор: 5 раз"


@pytest.mark.parametrize("args, слово", [
    ({"span": 1}, "либо"),
    ({"span": 1, "times": 2, "minutes": 3}, "либо"),
    ({"span": 0, "times": 2}, "хотя бы один"),
    ({"span": 1, "times": 0}, "от 1"),
    ({"span": 1, "minutes": 0}, "минут"),
    ({"span": 1, "times": 2, "pause_min": 3}, "пар"),
    ({"span": 1, "times": 2, "pause_min": 5, "pause_max": 1}, "пауза"),
])
def test_плохой_повтор_отвергается(args, слово):
    with pytest.raises(steps.StepError, match=слово):
        steps.normalize_steps([{"kind": "loop", "args": args}, {"kind": "unlock", "args": {}}])


def test_тело_за_концом_сценария_и_вложенный_повтор():
    with pytest.raises(steps.StepError, match="за концом"):
        steps.normalize_steps([_loop(3, times=2), {"kind": "unlock", "args": {}}])
    with pytest.raises(steps.StepError, match="внутри повтора"):
        steps.normalize_steps([_loop(2, times=2), _loop(1, times=2), {"kind": "unlock", "args": {}}])


# ------------------------------------------------------------------ код

def test_код_повтора_с_отступом_тела_и_картой_строк():
    code, lm = codegen.render_mapped(META, {}, _сценарий(), today=date(2026, 1, 1))
    compile(code, "s.py", "exec")
    lines = code.split("\n")
    head = next(i for i, l in enumerate(lines, 1) if "ctx.loop(" in l)
    assert lines[head - 1].strip() == "for _ in ctx.loop(times=3, pause=(1, 2), watch=True):"
    assert lines[head].startswith(" " * 8) and "ctx.swipe(" in lines[head]
    assert lines[head + 1].startswith(" " * 8) and 'ctx.key("back")' in lines[head + 1]
    assert lines[head + 2].startswith(" " * 4 + "ctx.sleep")
    assert [lm[head], lm[head + 1], lm[head + 2], lm[head + 3]] == [1, 2, 3, 4]


def test_повтор_по_минутам_и_развилка_в_теле_компилируются():
    items = steps.normalize_steps([
        _loop(1, minutes=10),
        {"kind": "branch", "args": {"name": "где"},
         "arms": [{"name": "лента", "any": ['text="Лента"'], "run": "blk"}]},
    ])
    code = codegen.render(META, {}, items, today=date(2026, 1, 1))
    compile(code, "s.py", "exec")
    assert "for _ in ctx.loop(minutes=10):" in code
    assert '            ctx.run("blk")' in code


# ------------------------------------------------------------------ ctx.loop

def _ctx(monkeypatch):
    ctx = DeviceContext("s", logger=lambda m: None)
    monkeypatch.setattr(ctx, "sleep", lambda s: None)
    return ctx


def test_loop_по_числу_раз(monkeypatch):
    assert list(_ctx(monkeypatch).loop(times=4)) == [0, 1, 2, 3]


def test_loop_по_минутам(monkeypatch):
    часы = iter([0, 0, 30, 61, 200])
    monkeypatch.setattr("farm.context.time.monotonic", lambda: next(часы))
    assert list(_ctx(monkeypatch).loop(minutes=1)) == [0, 1]


def test_loop_пауза_между_кругами_и_сторож(monkeypatch):
    ctx = _ctx(monkeypatch)
    паузы, сторож = [], []
    monkeypatch.setattr(ctx, "sleep", паузы.append)
    monkeypatch.setattr(ctx, "current_app", lambda: "com.vk")
    monkeypatch.setattr(ctx, "on_track", lambda pkg: сторож.append(pkg))
    list(ctx.loop(times=3, pause=(1, 2), watch=True))
    assert len(паузы) == 2 and all(1 <= p <= 2 for p in паузы)
    assert сторож == ["com.vk", "com.vk"]


def test_loop_прерывается_отменой(monkeypatch):
    отмена = {"n": 0}

    def cancel():
        отмена["n"] += 1
        return отмена["n"] > 2

    ctx = DeviceContext("s", logger=lambda m: None, cancel_check=cancel)
    from farm.context import Cancelled
    with pytest.raises(Cancelled):
        list(ctx.loop(times=100))


def test_loop_без_меры_ошибка(monkeypatch):
    with pytest.raises(ValueError):
        list(_ctx(monkeypatch).loop())


# ------------------------------------------------------------------ запуск с шага

class Rec:
    def __init__(self):
        self.calls = []

    def key(self, name):
        self.calls.append(("key", name))

    def swipe(self, *a):
        self.calls.append(("swipe",))

    def sleep(self, s):
        self.calls.append(("sleep", s))

    def loop(self, times=None, minutes=None, pause=None, watch=False):
        return range(times or 2)


def _module(tmp_path):
    code, lm = codegen.render_mapped(META, {}, _сценарий(), today=date(2026, 1, 1))
    path = tmp_path / "s.py"
    path.write_text(code, "utf-8")
    mod = types.ModuleType("s_mod")
    exec(compile(code, str(path), "exec"), mod.__dict__)
    return types.SimpleNamespace(path=str(path), module=mod), lm


def test_весь_сценарий_крутит_тело(tmp_path):
    sc, _ = _module(tmp_path)
    rec = Rec()
    sc.module.run(rec)
    assert rec.calls.count(("swipe",)) == 3


def test_проверка_шага_внутри_повтора_один_раз(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec()
    stepflow.module_from_step(sc, lm, 2, 3).run(rec)
    assert rec.calls == [("swipe",)]


def test_проверка_заголовка_повтора_один_круг(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec()
    stepflow.module_from_step(sc, lm, 1, 2).run(rec)
    assert rec.calls == [("swipe",), ("key", "back")]


def test_запуск_с_повтора_крутит_и_идёт_дальше(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec()
    stepflow.module_from_step(sc, lm, 1).run(rec)
    assert rec.calls.count(("swipe",)) == 3 and rec.calls[-1] == ("sleep", 1)


def test_запуск_с_середины_тела_проходит_его_раз(tmp_path):
    sc, lm = _module(tmp_path)
    rec = Rec()
    stepflow.module_from_step(sc, lm, 3).run(rec)
    assert rec.calls == [("key", "back"), ("sleep", 1)]


# ------------------------------------------------------------------ журнал

def test_повторные_шаги_не_раздувают_журнал():
    job = runner_mod.Job(id="j", scenario_key="s", scenario_name="s", serial="A", device_name="A", params={})
    labels = ["домой", "повтор", "свайп", "назад"]
    runner_mod._open_step(job, 0, labels)
    for _ in range(50):
        for i in (1, 2, 3):
            runner_mod._open_step(job, i, labels)
    assert len(job.timeline) == 4
    assert job.timeline[-1]["i"] == 3 and job.timeline[-1]["n"] == 50
    assert sum("▶ шаг" in line for line in job.lines) == 4
