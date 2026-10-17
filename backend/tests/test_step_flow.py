"""Ход по шагам: трассировка, запуск с шага N, необязательные шаги, объяснение ошибок."""
import types
from datetime import date

import pytest

from farm import control, stepflow
from farm.context import DeviceContext, StepFailed
from farm.explain import explain
from farm.recorder import codegen, steps

META = {"name": "Т", "description": "", "watch_popups": False, "human": False}


def _steps():
    return [steps.normalize_step({"kind": "key", "args": {"name": "home"}}),
            steps.normalize_step({"kind": "key", "args": {"name": "back"}}),
            steps.normalize_step({"kind": "sleep", "args": {"seconds": 1}})]


def _scenario(tmp_path, items=None):
    code, lm = codegen.render_mapped(META, {}, items or _steps(), today=date(2026, 1, 1))
    path = tmp_path / "s.py"
    path.write_text(code, "utf-8")
    mod = types.ModuleType("s_mod")
    exec(compile(code, str(path), "exec"), mod.__dict__)
    return types.SimpleNamespace(path=str(path), module=mod), lm


class Rec:
    def __init__(self):
        self.calls = []

    def key(self, name):
        self.calls.append(("key", name))

    def sleep(self, s):
        self.calls.append(("sleep", s))


def test_трассировщик_сообщает_шаги_по_порядку(tmp_path):
    sc, lm = _scenario(tmp_path)
    seen = []
    with stepflow.StepTracer(sc.module.run.__code__, lm, seen.append):
        sc.module.run(Rec())
    assert seen == [0, 1, 2]


def test_запуск_с_шага_режет_предыдущие(tmp_path):
    sc, lm = _scenario(tmp_path)
    rec = Rec()
    stepflow.module_from_step(sc, lm, 1).run(rec)
    assert rec.calls == [("key", "back"), ("sleep", 1)]


def test_запуск_с_шага_сохраняет_строки_для_трассировки(tmp_path):
    sc, lm = _scenario(tmp_path)
    mod = stepflow.module_from_step(sc, lm, 2)
    seen = []
    with stepflow.StepTracer(mod.run.__code__, lm, seen.append):
        mod.run(Rec())
    assert seen == [2]


def test_запуск_с_шага_без_карты_и_за_пределами(tmp_path):
    sc, lm = _scenario(tmp_path)
    with pytest.raises(ValueError, match="записанным"):
        stepflow.module_from_step(sc, {}, 1)
    with pytest.raises(ValueError, match="нет шага"):
        stepflow.module_from_step(sc, lm, 9)
    assert stepflow.module_from_step(sc, lm, 0) is sc.module


def test_развилка_целиком_вырезается_или_остаётся(tmp_path):
    items = [steps.normalize_step({"kind": "branch", "args": {"name": "в"},
                                   "arms": [{"name": "а", "any": ['text="Х"'], "run": "blk"}]}),
             steps.normalize_step({"kind": "key", "args": {"name": "back"}})]
    sc, lm = _scenario(tmp_path, items)

    class C(Rec):
        def which_screen(self, *a, **k):
            raise AssertionError("развилка должна быть вырезана")

        def run(self, key):
            raise AssertionError

    stepflow.module_from_step(sc, lm, 1).run(C())


def test_codegen_необязательный_и_повтор():
    items = [steps.normalize_step({"kind": "key", "args": {"name": "back"},
                                   "optional": True, "retries": 2})]
    code = codegen.render(META, {}, items, today=date(2026, 1, 1))
    assert 'ctx.attempt(lambda: ctx.key("back"), retries=2, optional=True, what="шаг 1")' in code
    compile(code, "x", "exec")


def test_у_шага_без_флагов_ключей_нет():
    step = steps.normalize_step({"kind": "key", "args": {"name": "back"}})
    assert "optional" not in step and "retries" not in step


@pytest.mark.parametrize("raw", [{"kind": "sleep", "args": {"seconds": 1}, "optional": True},
                                 {"kind": "expect", "args": {"name": "х"}, "retries": 1,
                                  "any": ['text="а"']}])
def test_гибкость_только_действиям(raw):
    with pytest.raises(steps.StepError):
        steps.normalize_step(raw)


def test_retries_границы():
    for bad in (6, -1, "x"):
        with pytest.raises(steps.StepError):
            steps.normalize_step({"kind": "key", "args": {"name": "b"}, "retries": bad})


def _ctx(monkeypatch):
    ctx = DeviceContext("s", logger=lambda m: None)
    monkeypatch.setattr(ctx, "sleep", lambda s: None)
    monkeypatch.setattr(control, "save_screenshot", lambda *a, **k: None)
    marks = []
    ctx.step_mark = marks.append
    return ctx, marks


def test_attempt_повторяет_и_успевает(monkeypatch):
    ctx, marks = _ctx(monkeypatch)
    n = []

    def flaky():
        n.append(1)
        if len(n) < 3:
            raise StepFailed("нет")
        return "ок"

    assert ctx.attempt(flaky, retries=2) == "ок"
    assert marks == ["retried", "retried"]


def test_attempt_необязательный_пропускает(monkeypatch):
    ctx, marks = _ctx(monkeypatch)

    def bad():
        raise StepFailed("нет")

    assert ctx.attempt(bad, retries=1, optional=True) is None
    assert marks == ["retried", "skipped"]


def test_attempt_обязательный_падает_исходной_ошибкой(monkeypatch):
    ctx, _ = _ctx(monkeypatch)

    def bad():
        raise StepFailed("нет")

    with pytest.raises(StepFailed, match="нет"):
        ctx.attempt(bad, retries=1)


def test_attempt_не_глотает_отмену(monkeypatch):
    from farm.context import Cancelled
    ctx, _ = _ctx(monkeypatch)

    def cancel():
        raise Cancelled("x")

    with pytest.raises(Cancelled):
        ctx.attempt(cancel, retries=3, optional=True)


def test_slow_mo_растягивает_sleep(monkeypatch):
    import farm.context as c
    ctx = DeviceContext("s", logger=lambda m: None)
    ctx.speed = 0.5
    slept = []
    monkeypatch.setattr(c.time, "sleep", lambda s: slept.append(s))
    clock = iter(range(0, 1000))
    monkeypatch.setattr(c.time, "time", lambda: next(clock) * 0.1)
    ctx.sleep(1)
    assert sum(slept) >= 1.5


def test_explain_таймаут_против_отказа():
    t = explain("не найден элемент {'text': 'Ок'} за 10 с")
    assert t["timeout"] and t["kind"] == "timeout" and "10 с" in t["title"]
    w = explain("ожидал экран «поиск», вижу com.a: [Войти, Регистрация]")
    assert not w["timeout"] and w["kind"] == "wrong_screen"
    assert "«поиск»" in w["title"] and "Войти" in w["hint"]
    assert explain("uiautomator2 недоступен на этом устройстве")["kind"] == "device"
    assert explain("блок «x» не найден в папке сценариев")["kind"] == "block"
    assert explain("")["kind"] == "other"


def test_слабый_якорь_только_системная_панель():
    from farm.context import is_weak_anchor
    sys_ = {"resourceId": "com.android.systemui:id/status_bar"}
    assert is_weak_anchor([sys_, {"resourceId": "com.android.systemui:id/x"}])
    assert not is_weak_anchor([sys_, {"text": "Каталог"}])
    assert not is_weak_anchor([])


def test_expect_на_системной_панели_помечает_вслепую(monkeypatch):
    ctx = DeviceContext("s", logger=lambda m: None)
    marks = []
    ctx.step_mark = marks.append
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "_wait_features", lambda f, t: True)
    ctx.expect_screen("экран", any=[{"resourceId": "com.android.systemui:id/status_bar"}])
    assert marks == ["blind"]
    marks.clear()
    ctx.expect_screen("экран", any=[{"text": "Каталог"}])
    assert marks == []


def test_валидация_предупреждает_о_слабом_якоре():
    from farm.recorder.validate import validate
    r = validate({"meta": {"name": "Т"}, "steps": [
        {"kind": "expect", "args": {"name": "s"},
         "any": ['resourceId="com.android.systemui:id/status_bar"']}]})
    assert r["ok"] and "системную панель" in r["warnings"][0]["text"]
