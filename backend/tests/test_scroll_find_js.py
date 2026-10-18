"""«Листать, пока не найдётся» в конструкторе (recorder.js) — под node.

Владелец: «не всегда нужно; человек не должен удивляться „что это“». Поле
выключено по умолчанию, включённое видно в строке шага, а после записанного
свайпа панель только предлагает его — сама не включает.
"""
import json

from farm.recorder import codegen, steps
from test_scope_js import like_ids, node, payload

SWIPE_DOWN = {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.75, "x2": 0.5, "y2": 0.3}}


def click(**extra):
    out = {"kind": "click", "args": {}, "selector": {"call": "click", "args": 'text="Нравится"'}}
    out.update(extra)
    return out


def suggest(seq, index=None):
    index = len(seq) - 1 if index is None else index
    return node(f"console.log(JSON.stringify(recScrollSuggest({json.dumps(seq, ensure_ascii=False)}, "
                f"{index})));")


def test_подсказка_после_свайпа_по_ленте():
    assert suggest([SWIPE_DOWN, click()]) == "down"
    # пауза между свайпом и нажатием не мешает
    assert suggest([SWIPE_DOWN, {"kind": "sleep", "args": {"seconds": 1}}, click()]) == "down"
    up = {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.3, "x2": 0.5, "y2": 0.8}}
    assert suggest([up, click()]) == "up"


def test_подсказки_нет_без_свайпа_по_ленте():
    side = {"kind": "swipe", "args": {"x1": 0.9, "y1": 0.5, "x2": 0.1, "y2": 0.55}}
    tiny = {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.5, "x2": 0.5, "y2": 0.45}}
    tap = {"kind": "tap", "args": {"x": 0.5, "y": 0.5}}
    assert suggest([side, click()]) == ""          # вбок — это не лента
    assert suggest([tiny, click()]) == ""          # едва сдвинул
    assert suggest([tap, click()]) == ""
    assert suggest([click()]) == ""
    assert suggest([SWIPE_DOWN, tap, click()]) == ""
    # уже включено, отказались, шаг из файла, свайп в другом блоке
    assert suggest([SWIPE_DOWN, click(scroll={"dir": "down", "max": 5})]) == ""
    assert suggest([SWIPE_DOWN, click(scrollNo=True)]) == ""
    assert suggest([SWIPE_DOWN, click(adopted=True)]) == ""
    assert suggest([dict(SWIPE_DOWN, parent=7), click()]) == ""
    assert suggest([SWIPE_DOWN, click()], 0) == ""


def test_по_умолчанию_не_листает_и_сама_не_включает():
    got = node(f"""
    const steps = [{json.dumps(SWIPE_DOWN)}, {json.dumps(click(), ensure_ascii=False)}];
    steps.forEach((s, i) => {{ s.id = i + 1; }});
    REC.steps = steps;
    const html = recScrollEditor(steps[1], 1);
    console.log(JSON.stringify([html, steps[1].scroll || null, recScrollBadge(steps[1])]));""")
    html, scroll, badge = got
    assert scroll is None and badge == ""
    assert "Если не видно на экране" in html
    assert '<option value="" selected>не листать</option>' in html
    assert "листать вниз" in html and "листать вверх" in html
    assert "Шаг ищет только на том, что сейчас видно на экране." in html
    # подсказка — вопрос с кнопкой, а не включённое поле
    assert "Вы листали перед этим нажатием — включить «листать, пока не найдётся»?" in html
    assert "recSetScroll(2, 'dir', 'down')" in html and "Не надо" in html


def test_включить_видно_в_строке_и_уходит_в_рецепт_и_код():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const s = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    s.id = 1; REC.steps = [{json.dumps(SWIPE_DOWN)}, s]; REC.steps[0].id = 2; REC.params = {{}};
    recRender = () => {{}}; recSave = () => {{}};
    recSetScroll(1, 'dir', 'down');
    const on = recScrollEditor(s, 1);
    recSetScroll(1, 'max', '3');
    recSetScroll(1, 'max', '99');      // мимо списка — не меняется
    const body = recPayload({{name: 'n'}});
    const back = recAdopt(body.steps[1], {{}});
    console.log(JSON.stringify([s.scroll, on, recScrollBadge(s), body.steps[1], recCode(s, 1),
        back.scroll]));""", dump)
    scroll, on, badge, step, code, back = got
    assert scroll == {"dir": "down", "max": 3}
    assert "листает ↓ до 3" in badge
    assert "Вы листали" not in on          # включили — подсказка ушла
    assert "до" in on and "каждое листание видно в журнале запуска" in on
    norm = steps.normalize_step(step)
    assert norm["scroll"] == {"dir": "down", "max": 3} and back == norm["scroll"]
    src = codegen.render({"name": "n", "watch_popups": False}, {}, [norm])
    assert src.strip().splitlines()[-1].split("  #")[0].strip() == code
    assert 'scroll_until=("down", 3)' in code


def test_выключить_и_не_надо():
    got = node(f"""
    const s = {json.dumps(click(scroll={"dir": "up", "max": 4}), ensure_ascii=False)};
    s.id = 1; const t2 = {json.dumps(click(), ensure_ascii=False)}; t2.id = 3;
    REC.steps = [{json.dumps(SWIPE_DOWN)}, s, t2]; REC.steps[0].id = 2;
    recRender = () => {{}}; recSave = () => {{}};
    const badge = recScrollBadge(s);
    recSetScroll(1, 'dir', '');
    REC.steps = [REC.steps[0], t2];
    recScrollNo(3);
    console.log(JSON.stringify([badge, s.scroll || null, recPayload({{name: 'n'}}).steps[1],
        recScrollSuggest(REC.steps, 1)]));""")
    badge, scroll, step, tip = got
    assert "листает ↑ до 4" in badge and scroll is None
    assert "scroll" not in step and "scrollNo" not in step
    assert tip == ""


def test_починка_шага_сохраняет_листание():
    dump = payload()
    ivan_like = like_ids(dump)[1]
    got = node(f"""
    const built = recBuildClickStep(DUMP.nodes[{ivan_like}], DUMP);
    console.log(JSON.stringify(repairBuildStep(built, {{scroll: {{dir: 'down', max: 6}}}}, null)));""",
               dump)
    assert got["scroll"] == {"dir": "down", "max": 6}
    assert steps.normalize_step(got)["scroll"] == {"dir": "down", "max": 6}
