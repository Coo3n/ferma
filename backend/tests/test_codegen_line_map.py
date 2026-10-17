"""Карта «строка сгенерированного .py → индекс шага» для разбора трейсбэков."""
import json
from datetime import date

from farm import config
from farm.recorder import codegen, save, steps

META = {"name": "Т", "description": "", "watch_popups": True, "human": True}
ВЕТКИ = [{"name": "онбординг", "any": ['text="Далее"'], "run": "skip_onboarding"},
         {"name": "каталог", "any": ['text="Каталог"'], "run": ""}]


def _шаги():
    return [
        steps.normalize_step({"kind": "unlock", "args": {}}),
        steps.normalize_step({"kind": "branch", "args": {"name": "после входа"},
                              "arms": ВЕТКИ}),
        steps.normalize_step({"kind": "key", "args": {"name": "back"}, "note": "назад"}),
    ]


def _строка(code: str, фрагмент: str) -> int:
    """1-based номер первой строки, содержащей фрагмент."""
    for i, line in enumerate(code.split("\n"), 1):
        if фрагмент in line:
            return i
    raise AssertionError(фрагмент)


def test_одиночные_шаги_и_многострочная_развилка():
    code, lm = codegen.render_mapped(META, {}, _шаги(), today=date(2026, 1, 1))
    assert lm[_строка(code, "ctx.unlock()")] == 0
    первая = _строка(code, "ветка = ctx.which_screen")
    последняя = _строка(code, "ctx.run(\"skip_onboarding\")")
    for n in range(первая, последняя + 1):
        assert lm[n] == 1
    assert lm[_строка(code, "ctx.key(")] == 2
    assert set(lm.values()) == {0, 1, 2}


def test_служебные_строки_не_отображаются():
    code, lm = codegen.render_mapped(META, {}, _шаги(), today=date(2026, 1, 1))
    for фрагмент in ("ctx.watch_popups()", "ctx.humanize()", "def run(ctx):", "NAME ="):
        assert _строка(code, фрагмент) not in lm


def test_render_совпадает_с_render_mapped():
    args = (META, {}, _шаги(), date(2026, 1, 1))
    assert codegen.render(*args) == codegen.render_mapped(*args)[0]


def test_line_map_переживает_сохранение(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    path = save.save("flow", META, {}, _шаги())
    raw = json.loads(save.recipe_path("flow").read_text("utf-8"))
    assert all(isinstance(k, str) for k in raw["line_map"])
    lm = save.load_line_map("flow")
    assert lm[_строка(path.read_text("utf-8"), "ctx.unlock()")] == 0
    assert all(isinstance(k, int) for k in lm)


def test_старый_рецепт_без_line_map(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    save.save("flow", META, {}, _шаги())
    p = save.recipe_path("flow")
    data = json.loads(p.read_text("utf-8"))
    del data["line_map"]
    p.write_text(json.dumps(data), "utf-8")
    assert save.load_line_map("flow") == {}
    assert save.load_recipe("flow")["steps"]
