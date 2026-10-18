"""Выбор «как искать» в конструкторе (recorder.js) — под node, без браузера.

Оператор видит все способы найти элемент, у каждого понятная пометка:
«✓ один на экране», «⚠ похожих: 3», «⚠ текст меняется», «2-й из 3».
"""
import json
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"

PRELUDE = r"""
const vm = require('vm'), fs = require('fs');
const noop = () => {};
const STR = JSON.parse(fs.readFileSync(process.argv[1] + '/../strings/ru.json', 'utf8'));
const ctx = {console, localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
    document: {querySelector: () => null, addEventListener: noop, getElementById: () => null,
               readyState: 'complete'},
    setTimeout, clearTimeout, Image: function () {},
    esc: v => String(v ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])),
    t: (k, v) => {
        const s = STR[k];
        if (s == null) throw new Error('нет строки ' + k);
        return v ? s.replace(/\{(\w+)\}/g, (m, n) => (v[n] != null ? v[n] : m)) : s;
    }};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1] + '/recorder.js', 'utf8'), ctx, {filename: 'recorder'});
ctx.run = code => vm.runInContext(code, ctx);
"""


def node(body: str):
    out = subprocess.run(
        [require_node(), "-e", PRELUDE + "vm.runInContext(" + json.dumps(body) + ", ctx);", str(JS)],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


LIKES = """[
  {call: 'click', args: 'resourceId="app:id/like", instance=1', matches: 1, fragile: true, dynamic: false, nth: [2, 3]},
  {call: 'click', args: 'resourceId="app:id/like"', matches: 3, fragile: false, dynamic: false},
  {call: 'click', args: 'description="Нравится"', matches: 3, fragile: false, dynamic: false},
  {call: 'click', args: 'text="125"', matches: 1, fragile: false, dynamic: true},
  {call: 'tap', args: '0.1, 0.4', matches: 1, fragile: true, dynamic: false}]"""


def test_пометки_кандидатов_словами():
    got = node(f"""
    const a = {LIKES};
    console.log(JSON.stringify(a.map(recSelMark)));""")
    assert got[0] == "✓ 2-й из 3 похожих"
    assert got[1] == "⚠ похожих: 3"
    assert got[3] == "✓ один на экране · ⚠ текст меняется"


def test_номер_по_счёту_читается_по_человечески():
    got = node("""console.log(JSON.stringify(recFeatText('resourceId="app:id/like_button", instance=1')));""")
    assert "2-й по счёту" in got and "like button" in got


def test_как_искать_показывает_все_способы_нажатия_но_не_координаты():
    """Координаты — отдельный слой шага; выбор «tap» как основного ронял бы
    сохранение (steps.py принимает у click только call=click)."""
    html = node(f"""
    const step = {{id: 7, kind: 'click', args: {{}}, selector: {{call: 'click', args: 'resourceId="app:id/like", instance=1'}},
                  alts: {LIKES}}};
    console.log(JSON.stringify(recAlts(step)));""")
    assert html.count('type="radio"') == 4
    assert "0.1, 0.4" not in html
    assert "2-й из 3 похожих" in html and "похожих: 3" in html and "текст меняется" in html


def test_меняющийся_текст_не_попадает_в_запасные_сам():
    got = node(f"""
    const step = {{kind: 'click', selector: {{call: 'click', args: 'resourceId="app:id/like", instance=1'}}, alts: {LIKES}}};
    console.log(JSON.stringify(recFallbacks(step)));""")
    assert 'text="125"' not in got
    assert got == ['resourceId="app:id/like"', 'description="Нравится"']


def test_меняющийся_текст_не_идёт_в_слой_поиска_по_тексту():
    got = node("""console.log(JSON.stringify([
        recTexts({text: '125', description: 'Нравится', textDynamic: true}),
        recTexts({text: 'Войти', description: ''})]));""")
    assert got == [["Нравится"], ["Войти"]]


def test_предупреждение_шага_для_номера_и_для_меняющегося_текста():
    got = node(f"""
    const a = {LIKES};
    console.log(JSON.stringify([recSelWarn(a[0]), recSelWarn(a[1]), recSelWarn(a[3]),
        recSelWarn({{call: 'click', args: 'x="y"', matches: 1, fragile: false}}), recSelWarn({{matches: null}})]));""")
    nth, many, dyn, ok, unknown = got
    assert "2-й" in nth and "3" in nth
    assert "подходит 3 элемента" in many
    assert "меняется" in dyn
    assert ok == "" and unknown == ""


def test_выбор_способа_пересчитывает_предупреждение():
    got = node(f"""
    REC.steps = [{{id: 7, kind: "click", args: {{}}, selector: {{call: "click", args: "x"}}, alts: {LIKES}}}];
    recRender = () => {{}}; recSave = () => {{}};
    recPickSelector(7, 3);
    const w1 = REC.steps[0].warn;
    recPickSelector(7, 0);
    console.log(JSON.stringify([w1, REC.steps[0].warn, REC.steps[0].selector]));""")
    assert "меняется" in got[0]
    assert "2-й" in got[1]
    assert got[2] == {"call": "click", "args": 'resourceId="app:id/like", instance=1'}


def test_якорь_экрана_не_берёт_меняющийся_текст():
    got = node("""
    const dump = {nodes: [
        {selectors: [{call: 'click', args: 'text="12:45"', matches: 1, fragile: false, dynamic: true}]},
        {selectors: [{call: 'click', args: 'text="Лента"', matches: 1, fragile: false, dynamic: false}]}]};
    console.log(JSON.stringify(recAnchorFeatures(dump)));""")
    assert got == ['text="Лента"']


def test_при_равной_площади_берётся_узел_поверх():
    """Обёртка и кнопка с одинаковыми рамками: нажимали кнопку (она позже в дампе)."""
    got = node("""
    const dump = {nodes: [
        {id: 0, bounds: [0, 0, 1, 1]},
        {id: 1, bounds: [0.1, 0.1, 0.3, 0.2]},
        {id: 2, bounds: [0.1, 0.1, 0.3, 0.2]},
        {id: 3, bounds: [0.5, 0.5, 0.6, 0.6]}]};
    console.log(JSON.stringify([recHit(0.2, 0.15, dump).id, recHit(0.9, 0.9, dump).id]));""")
    assert got == [2, 0]


def test_tap_в_выборе_основного_не_ломает_шаг():
    """Даже если индекс указывает на координаты (старая разметка), селектор шага
    остаётся вызовом click — иначе сохранение получило бы 400."""
    got = node(f"""
    REC.steps = [{{id: 7, kind: "click", args: {{}}, selector: {{call: "click", args: "x=1"}}, alts: {LIKES}}}];
    recRender = () => {{}}; recSave = () => {{}};
    recPickSelector(7, 4);
    console.log(JSON.stringify(REC.steps[0].selector));""")
    assert got == {"call": "click", "args": "x=1"}
