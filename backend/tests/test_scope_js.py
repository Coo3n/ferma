"""«Внутри» / «рядом с» в конструкторе (recorder.js, repair.js) — под node.

Оператор нажал лайк, а лайков в ленте три одинаковых. Панель сама предлагает
«рядом с: «Иван Петров»» вместо хрупкого «2-й из 3», показывает
«✓ один на экране» и даёт указать ориентир пальцем на зеркале. Выбор в
браузере обязан совпадать с тем, что farm/ui/scope.py нажмёт на прогоне.
"""
import json
import subprocess
from pathlib import Path

from _node import require_node
from farm.context import normalize_target
from farm.recorder import codegen, steps
from farm.ui import scope, selectors, tree
from test_scope import FEED, H, W

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"

PRELUDE = r"""
const vm = require('vm'), fs = require('fs');
const noop = () => {};
const STR = JSON.parse(fs.readFileSync(process.argv[1] + '/../strings/ru.json', 'utf8'));
const ctx = {console, localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
    document: {querySelector: () => null, addEventListener: noop, getElementById: () => null,
               readyState: 'complete'},
    setTimeout, clearTimeout, Image: function () {},
    toast: (m, k) => { ctx.toasts.push([m, k]); }, toasts: [],
    esc: v => String(v ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])),
    t: (k, v) => {
        const s = STR[k];
        if (s == null) throw new Error('нет строки ' + k);
        return v ? s.replace(/\{(\w+)\}/g, (m, n) => (v[n] != null ? v[n] : m)) : s;
    }};
ctx.window = ctx;
vm.createContext(ctx);
for (const f of ['recorder', 'blocks', 'repair'])
    vm.runInContext(fs.readFileSync(process.argv[1] + '/' + f + '.js', 'utf8'), ctx, {filename: f});
"""


def node(body: str, dump=None):
    pre = PRELUDE
    if dump is not None:
        pre += "ctx.DUMP = " + json.dumps(dump, ensure_ascii=False) + ";\n"
    out = subprocess.run(
        [require_node(), "-e", pre + "vm.runInContext(" + json.dumps(body) + ", ctx);", str(JS)],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def payload():
    return {"nodes": selectors.to_payload(tree.parse(FEED, W, H)), "screenshot": "data:x"}


def like_ids(dump):
    return [n["id"] for n in dump["nodes"] if n["resourceId"] == "app:id/like"]


def test_подсказки_для_лайка_под_постом():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const t = DUMP.nodes[{ivan_like}];
    console.log(JSON.stringify(recScopeSuggest(DUMP.nodes, t, 'resourceId="app:id/like"')));""", dump)
    kinds = {s["kind"]: s for s in got}
    # контейнер поста — без уникального id (у всех app:id/post): «внутри» нет
    assert "within" not in kinds
    near = kinds["near"]
    # ближайшая уникальная устойчивая надпись того же поста; «4 ч» — меняется
    assert near["args"] == 'text="Иван Петров"' and near["name"] == "Иван Петров"
    assert near["base"] == 'resourceId="app:id/like"'
    # на прогоне scope.pick с этим ориентиром нажмёт ровно этот лайк
    ns = tree.parse(FEED, W, H)
    picked, _ = scope.pick(ns, {"resourceId": "app:id/like"}, near=scope.parse_args(near["args"]))
    assert picked.id == ivan_like


def test_внутри_предлагается_для_контейнера_с_уникальным_id():
    dump = payload()
    story_like = like_ids(dump)[3]
    got = node(f"""
    console.log(JSON.stringify(recScopeSuggest(DUMP.nodes, DUMP.nodes[{story_like}],
        'description="Нравится"')));""", dump)
    assert got[0]["kind"] == "within" and got[0]["args"] == 'resourceId="app:id/stories"'
    assert got[0]["name"] == "stories"


def test_уникальная_цель_подсказок_не_получает():
    dump = payload()
    got = node(f"""
    console.log(JSON.stringify(recScopeSuggest(DUMP.nodes, DUMP.nodes[1],
        'text="Анна"')));""", dump)
    assert got == []


def test_шаг_записи_берёт_ориентир_вместо_номера():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    console.log(JSON.stringify({{sel: s.selector, near: s.near, within: s.within || null,
        warn: s.warn, scopes: (s.scopes || []).length}}));""", dump)
    assert got["sel"]["args"] == 'resourceId="app:id/like"'
    assert got["near"] == 'text="Иван Петров"' and got["within"] is None
    assert got["warn"] == "" and got["scopes"] >= 1


def test_как_искать_показывает_выбор_места_словами():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    html = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    s.id = 5;
    console.log(JSON.stringify(recAlts(s)));""", dump)
    assert "рядом с: «Иван Петров»" in html
    assert "везде на экране" in html
    assert "указать на экране" in html.lower()
    assert "✓ один на экране" in html
    assert "near=" not in html.split("title=")[0]     # без кода на виду


def test_выбор_везде_и_обратно():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    s.id = 5; REC.steps = [s];
    recRender = () => {{}}; recSave = () => {{}};
    recPickScope(5, -1);
    const off = [s.near || null, s.warn];
    recPickScope(5, 0);
    console.log(JSON.stringify([off, s.near, s.warn]));""", dump)
    off, near, warn = got
    assert off[0] is None and "похожих" in off[1] or "подходит" in off[1]
    assert near == 'text="Иван Петров"' and warn == ""


def test_указать_на_экране_ориентир_пальцем():
    dump = payload()
    likes = like_ids(dump)
    oleg = next(n for n in dump["nodes"] if n["text"] == "Олег")
    b = oleg["bounds"]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{likes[2]}], DUMP);
    s.id = 9; REC.steps = [s]; REC.dump = DUMP; REC.on = true;
    recRender = () => {{}}; recSave = () => {{}};
    recPickScope(9, -1);
    recScopeOnScreen(9);
    const waiting = REC.scopePick;
    const handled = recScopeTap({{type: 'tap', x: {(b[0] + b[2]) / 2}, y: {(b[1] + b[3]) / 2}}});
    console.log(JSON.stringify([waiting, handled, REC.scopePick || null, s.near, s.warn,
        recSelScopeMark(s), toasts]));""", dump)
    waiting, handled, after, near, warn, mark, toasts = got
    assert waiting == 9 and handled is True and after is None
    assert near == 'text="Олег"' and warn == ""
    assert mark == "✓ один на экране"


def test_указать_на_меняющуюся_надпись_нельзя():
    dump = payload()
    likes = like_ids(dump)
    hours = next(n for n in dump["nodes"] if n["text"] == "4 ч")
    b = hours["bounds"]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{likes[1]}], DUMP);
    s.id = 9; REC.steps = [s]; REC.dump = DUMP; REC.on = true;
    recRender = () => {{}}; recSave = () => {{}};
    recScopeOnScreen(9);
    recScopeTap({{type: 'tap', x: {(b[0] + b[2]) / 2}, y: {(b[1] + b[3]) / 2}}});
    console.log(JSON.stringify([s.near, toasts.length, toasts[toasts.length - 1][1]]));""", dump)
    # ориентир остался прежним, человеку сказали почему
    assert got[0] == 'text="Иван Петров"' and got[1] >= 1 and got[2] == "bad"


def test_выбор_совпадает_с_прогоном_для_любого_ориентира():
    """recScopePick (браузер) и scope.pick (прогон) выбирают один узел."""
    dump = payload()
    ns = tree.parse(FEED, W, H)
    cases = [('resourceId="app:id/like"', {"near": 'text="Олег"'}),
             ('resourceId="app:id/like"', {"near": 'resourceId="app:id/stories"'}),
             ('description="Нравится"', {"within": 'resourceId="app:id/stories"'}),
             ('resourceId="app:id/author"', {"near": 'resourceId="app:id/stories"'}),
             ('resourceId="app:id/like", instance=1', {"within": 'resourceId="app:id/feed"'})]
    got = node(f"""
    const cases = {json.dumps(cases, ensure_ascii=False)};
    console.log(JSON.stringify(cases.map(([a, s]) => {{
        const n = recScopePick(DUMP.nodes, a, s);
        return n ? n.id : null; }})));""", dump)
    want = []
    for args, sc in cases:
        kw = {k: scope.parse_args(v) for k, v in sc.items()}
        picked, _ = scope.pick(ns, scope.parse_args(args), **kw)
        want.append(picked.id if picked else None)
    assert got == want


def test_рецепт_и_код_несут_место_поиска():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    s.id = 1; REC.steps = [s]; REC.params = {{}};
    const body = recPayload({{name: 'n'}});
    const back = recAdopt(body.steps[0], {{}});
    console.log(JSON.stringify([body.steps[0], recCode(s, 0), back.near]));""", dump)
    step, code, back = got
    norm = steps.normalize_step(step)
    assert norm["near"] == 'text="Иван Петров"' and back == norm["near"]
    src = codegen.render({"name": "n", "watch_popups": False}, {}, [norm])
    assert src.strip().splitlines()[-1].split("  #")[0].strip() == code


def test_починка_переносит_место_поиска_и_шлёт_его_в_патч():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const built = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    const step = repairBuildStep(built, {{param: null}}, null);
    const plain = recBuildClickStep(DUMP.nodes.find(n => n.text === 'Анна'), DUMP);
    const cleared = repairBuildStep(plain, {{near: 'text="Мария"'}}, null);
    console.log(JSON.stringify([step, repairPatchFromStep(step), cleared,
        repairPatchFromStep(cleared)]));""", dump)
    step, patch, cleared, patch2 = got
    assert step["near"] == 'text="Иван Петров"'
    steps.normalize_step(step)
    assert patch["near"] == {"text": "Иван Петров"} and patch["within"] is None
    assert normalize_target(patch) == patch
    # у нового шага места нет: старое не переносится и снимается у ждущего запуска
    assert cleared.get("near") is None and patch2["near"] is None
    assert normalize_target(patch2) == patch2
    assert "near" not in steps.normalize_step(cleared)


def test_точка_шага_записывается_от_места_и_прогон_попадает_в_тот_же_лайк():
    """Слой «точка» с местом: смещение от ориентира, а не угол экрана."""
    from test_scope import Ctx
    dump = payload()
    ivan_like = like_ids(dump)[1]
    story_like = like_ids(dump)[3]
    got = node(f"""
    const a = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    const b = recBuildClickStep(DUMP.nodes[{story_like}], DUMP);
    a.id = 1; REC.steps = [a]; REC.params = {{}};
    const body = recPayload({{name: 'n'}});
    console.log(JSON.stringify([a.near, a.point_rel, b.within, b.point_rel, body.steps[0],
        recCode(a, 0), recAdopt(body.steps[0], {{}}).point_rel]));""", dump)
    near, rel, within, rel2, step, code, back = got
    assert near == 'text="Иван Петров"' and rel is not None and back == rel
    assert within == 'resourceId="app:id/stories"' and all(0 <= c <= 1 for c in rel2)
    norm = steps.normalize_step(step)
    assert norm["point_rel"] == rel
    src = codegen.render({"name": "n", "watch_popups": False}, {}, [norm])
    assert src.strip().splitlines()[-1].split("  #")[0].strip() == code
    # селектор и текст промахнулись — точка от «Иван Петров» всё равно его лайк
    ctx = Ctx()
    ctx.click_target(sel=[{"text": "нет"}], near={"text": "Иван Петров"}, at_rel=rel, timeout=0)
    assert ctx.taps == [(0.07, 0.57)]
    ctx = Ctx()
    ctx.click_target(sel=[{"text": "нет"}], within={"resourceId": "app:id/stories"},
                     at_rel=rel2, timeout=0)
    assert ctx.taps == [(0.05, 0.975)]


def test_везде_снимает_смещение_а_ориентир_пальцем_считает_своё():
    from test_scope import Ctx
    dump = payload()
    likes = like_ids(dump)
    oleg = next(n for n in dump["nodes"] if n["text"] == "Олег")
    b = oleg["bounds"]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{likes[2]}], DUMP);
    s.id = 9; REC.steps = [s]; REC.dump = DUMP; REC.on = true;
    recRender = () => {{}}; recSave = () => {{}};
    recPickScope(9, -1);
    const off = s.point_rel || null;
    recScopeOnScreen(9);
    recScopeTap({{type: 'tap', x: {(b[0] + b[2]) / 2}, y: {(b[1] + b[3]) / 2}}});
    console.log(JSON.stringify([off, s.near, s.point_rel]));""", dump)
    off, near, rel = got
    assert off is None and near == 'text="Олег"' and rel is not None
    ctx = Ctx()
    ctx.click_target(sel=[{"text": "нет"}], near={"text": "Олег"}, at_rel=rel, timeout=0)
    assert ctx.taps == [(0.07, 0.87)]
