"""Чистая логика починки шага (frontend/js/repair.js) и вынесенный из рекордера
построитель шага. Гоняется под node в vm с минимальными заглушками DOM; без
node тесты пропускаются."""
import json
import subprocess
from pathlib import Path

import pytest

from _node import require_node
from farm.context import normalize_target
from farm.recorder import steps as schema

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"


PRELUDE = r"""
const vm = require('vm'), fs = require('fs');
const noop = () => {};
const ctx = {console, localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
    document: {querySelector: () => null, addEventListener: noop, getElementById: () => null,
               readyState: 'complete'},
    setTimeout, clearTimeout, Image: function () {}};
ctx.window = ctx;
vm.createContext(ctx);
for (const f of ['recorder', 'repair'])
    vm.runInContext(fs.readFileSync(process.argv[1] + '/' + f + '.js', 'utf8'), ctx, {filename: f});
ctx.run = code => vm.runInContext(code, ctx);
"""


def node(body: str):
    out = subprocess.run([require_node(), "-e", PRELUDE + "vm.runInContext(" + json.dumps(body) + ", ctx);", str(JS)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


RECIPE = """{meta: {name: 'n'}, params: {}, screen_width: 1080,
  assets: {'01_click.png': 'AAA', '03_click.png': 'CCC'},
  steps: [
    {kind: 'click', args: {}, selector: {call: 'click', args: 'text="Войти"', fallbacks: ['resourceId="a:id/go"']},
     param: null, note: '«Войти»', texts: ['Войти'], point: [0.5, 0.5], crop: '01_click.png'},
    {kind: 'tap', args: {x: 0.1, y: 0.2}, selector: null, param: null, note: ''},
    {kind: 'click', args: {}, selector: {call: 'click', args: 'text="Дальше"', fallbacks: []},
     param: null, note: '«Дальше»', pos: {x: 1, y: 2}, crop: '03_click.png'}]}"""


def test_plan():
    got = node(f"""
    const r = {RECIPE};
    console.log(JSON.stringify([repairPlan(r, 0), repairPlan(r, 1), repairPlan(r, 9),
        repairPlan(r, -1), repairPlan(r, 1.5), repairPlan(null, 0)]));""")
    assert got[0] == {"ok": True, "kind": "click", "old": {
        "label": "«Войти»", "selector": 'text="Войти"', "texts": ["Войти"]}}
    assert got[1]["ok"] is False and got[1]["kind"] == "tap"
    for bad in got[2:]:
        assert bad["ok"] is False and bad["reason"]


def test_apply_immutable_and_only_that_step():
    got = node(f"""
    const r = {RECIPE};
    const before = JSON.stringify(r);
    const ns = {{kind: 'click', args: {{}}, selector: {{call: 'click', args: 'text="Х"', fallbacks: []}},
                param: null, note: 'Х', crop: '01_click.png'}};
    const n = repairApply(r, 0, ns, 'NEWCROP');
    const n2 = repairApply(r, 0, {{...ns, crop: undefined}}, '');
    console.log(JSON.stringify({{same: JSON.stringify(r) === before, n, n2,
        nsKept: ns.crop === '01_click.png'}}));""")
    assert got["same"] and got["nsKept"]
    n, orig = got["n"], node(f"console.log(JSON.stringify({RECIPE}))")
    assert n["steps"][1:] == orig["steps"][1:]
    assert n["steps"][0]["note"] == "Х"
    assert n["assets"] == {"01_click.png": "NEWCROP", "03_click.png": "CCC"}
    # без нового кропа старый файл выкидывается, чужой остаётся
    assert got["n2"]["assets"] == {"03_click.png": "CCC"}
    assert "crop" not in got["n2"]["steps"][0]


def test_build_step_keeps_pos_and_passes_backend_schema():
    got = node("""
    const node = {selectors: [{call: 'click', args: 'text="Ок"', matches: 1}, {call: 'click', args: 'resourceId="a:id/ok"', matches: 1}],
        bounds: [0.1, 0.2, 0.3, 0.4], text: 'Ок', description: '', resourceId: 'a:id/ok', 'class': 'x.Button'};
    const built = recBuildClickStep(node, {screenshot: 'data:x'});
    const old = {param: null, pos: [3, 4]};
    console.log(JSON.stringify(repairBuildStep(built, old, '01_click.png')));""")
    assert got["param"] is None and got["pos"] == [3, 4]
    assert got["selector"]["fallbacks"] == ['resourceId="a:id/ok"']
    assert got["texts"] == ["Ок"] and got["point"] == [0.2, 0.3]
    schema.normalize_step(got)      # то же, что примет /api/recorder/save


def test_patch_shape_accepted_by_normalize_target():
    got = node("""
    console.log(JSON.stringify([
        repairPatchFromStep({selector: {call: 'click', args: 'text="Вой\\\\"ти", instance=2',
            fallbacks: ['resourceId="a:id/go"', 'мусор']}, texts: ['Войти'], point: [0.25, 0.5]}),
        repairPatchFromStep({selector: {call: 'click', args: 'text="x"', fallbacks: []}}),
        repairPatchFromStep({selector: {call: 'click', args: '???'}, point: [2, 0]}),
        repairParseSel('a=1, b="c"'), repairParseSel('a=1 b=2')]));""")
    full, sel_only, junk, parsed, bad = got
    assert full == {"sel": [{"text": 'Вой"ти', "instance": 2}, {"resourceId": "a:id/go"}],
                    "text": ["Войти"], "at": [0.25, 0.5]}
    assert normalize_target(full) == full          # тот же валидатор, что на сервере
    # нет текстов -> text: [] стирает тексты старого шага (click_target
    # заменяет только присланные ключи)
    assert sel_only == {"sel": [{"text": "x"}], "text": []}
    assert normalize_target(sel_only) == sel_only
    # целиком пустая цель: ни одного ключа (сервер такую отверг бы 400)
    assert junk == {}
    assert "img" not in full
    assert parsed == {"a": 1, "b": "c"} and bad is None


def test_stale():
    got = node(f"""
    const r = {RECIPE};
    console.log(JSON.stringify([
        repairStale(r, 0, {{kind: 'click', selector: 'text="Войти"', texts: ['Войти']}}),
        repairStale(r, 0, {{kind: 'click', selector: 'text="Другое"'}}),
        repairStale(r, 0, {{kind: 'tap'}}),
        repairStale(r, 0, {{kind: 'click', texts: ['Войти'], selCount: 2}}),
        repairStale(r, 0, {{kind: 'click', texts: [], selCount: 2}}),
        repairStale(r, 0, {{kind: 'click', texts: ['Войти'], selCount: 1}}),
        repairStale(r, 7, null),
        repairStale(r, 0, null),
        repairExpected(r, 0, '{{"sel": [{{"text": "Войти"}}, {{"resourceId": "a:id/go"}}], "text": ["Войти"]}}'),
        repairExpected(r, 0, '')]));""")
    assert got[:8] == [False, True, True, False, True, True, True, False]
    assert got[8]["kind"] == "click" and got[8]["texts"] == ["Войти"] and len(got[8]["sel"]) == 2
    assert got[9]["selector"] == 'text="Войти"'


def test_recNoteTap_builds_same_step_as_before():
    """recNoteTap теперь зовёт recBuildClickStep; результат — прежний литерал."""
    got = node("""
    const sel = {call: 'click', args: 'text="Ок"', matches: 2, fragile: true};
    const nd = {id: 0, target: 0, selectors: [sel, {call: 'click', args: 'resourceId="i"', matches: 1}],
        bounds: [0.1, 0.2, 0.3, 0.4], text: 'Ок', description: 'ок-кнопка', resourceId: 'p:id/ok', 'class': 'a.B'};
    run('REC.dump = ' + JSON.stringify({screenshot: 'data:shot', nodes: [nd]}));
    run('REC.steps = []; recMaybeAnchor = () => {}; recRender = () => {}; recSave = () => {}; recCropStep = () => {}');
    run('recNoteTap({x: 0.2, y: 0.3})');
    console.log(JSON.stringify(run('REC.steps')));""")
    assert len(got) == 1
    step = got[0]
    assert step.pop("id") >= 1
    assert step == {
        "kind": "click", "args": {},
        "selector": {"call": "click", "args": 'text="Ок"'},
        "alts": [{"call": "click", "args": 'text="Ок"', "matches": 2, "fragile": True},
                 {"call": "click", "args": 'resourceId="i"', "matches": 1}],
        "note": "«Ок»", "bounds": [0.1, 0.2, 0.3, 0.4], "shot": "data:shot",
        "texts": ["Ок", "ок-кнопка"], "point": [0.2, 0.3],
        "warn": "под это описание подходит 2 элемента — шаг может нажать не то; элемент узнаётся ненадёжно — на другом телефоне может не найтись",
        "param": None}


def test_stale_compares_selector_dicts_not_count():
    got = node(f"""
    const r = {RECIPE};
    const exp = m => repairExpected(r, 0, m);
    const other = JSON.stringify({{sel: [{{text: 'Войти'}}, {{resourceId: 'a:id/OTHER'}}], text: ['Войти']}});
    const same = JSON.stringify({{sel: [{{resourceId: 'a:id/go'}}, {{text: 'Войти'}}], text: ['Войти']}});
    // выше индекс сдвинулся на клик с теми же текстами и тем же числом селекторов
    console.log(JSON.stringify([repairStale(r, 0, exp(other)), repairStale(r, 0, exp(same)),
        repairStale(r, 0, exp('')), repairStale(r, 0, exp(null))]));""")
    assert got == [True, False, False, False]      # без miss — сравнение с рецептом на открытии


# --- hold: только шаги, что рендерятся в click_target -------------------------------

def test_hold_refuses_plain_click_but_fail_mode_allows():
    got = node("""
    const plain = {kind: 'click', args: {}, selector: {call: 'click', args: 'text="A"', fallbacks: []}, note: ''};
    const withText = Object.assign({}, plain, {texts: ['A']});
    const r = {steps: [plain, withText]};
    console.log(JSON.stringify([repairPlan(r, 0, 'hold'), repairPlan(r, 1, 'hold'),
        repairPlan(r, 0, 'fail'), repairPlan(r, 0)]));""")
    assert got[0]["ok"] is False and got[0]["full"] is True
    assert got[0]["reason"].startswith("Запуск ждёт на шаге, где нажатие записано по описанию элемента")
    assert got[1]["ok"] is True and got[2]["ok"] is True and got[3]["ok"] is True


def test_click_target_predicate_matches_codegen():
    from farm.recorder.codegen import render_mapped
    sel = {"call": "click", "args": 'text="A"', "fallbacks": []}
    sel2 = {"call": "click", "args": 'text="A"', "fallbacks": ['resourceId="x"']}
    variants = [
        {}, {"texts": ["A"]}, {"texts": []}, {"crop": "01_click.png"}, {"crop": ""},
        {"point": [0.5, 0.5]}, {"point": [0.0, 0.0]}, {"point": []}, {"point": None},
        {"texts": ["A"], "crop": "c.png", "point": [0.1, 0.2]},
    ]
    steps = []
    for extra in variants:
        for s in (sel, sel2):
            steps.append({"kind": "click", "args": {}, "selector": s, "param": None, "note": "", **extra})
    verdicts = node(f"console.log(JSON.stringify({json.dumps(steps)}.map(repairRendersClickTarget)))")
    for step, js in zip(steps, verdicts):
        text, _ = render_mapped({"name": "n"}, {}, [step])
        assert js == ("ctx.click_target(" in text), step
    assert any(verdicts) and not all(verdicts)


# --- DOM-состояние: модалка, фокус, отмена, в vm с ручной заглушкой ------------------

HARNESS = r"""
const noop = () => {};
const H = {focus: [], calls: [], toasts: [], opens: 0, closes: 0, pend: {}, els: {}, modalReturn: null};
const BODY_IDS = ['rpStage', 'rpShot', 'rpLayer', 'rpHover', 'rpDiff', 'rpStatus'];
const ACT_IDS = ['rpCancel', 'rpSave', 'rpRetry', 'rpClose'];
class El {
    constructor(id) { this.id = id; this.cl = new Set(); this._h = ''; this.textContent = '';
        this.dataset = {}; this.title = ''; this.disabled = false; this.style = {};
        this.classList = {add: c => this.cl.add(c), remove: c => this.cl.delete(c),
            contains: c => this.cl.has(c)}; }
    get innerHTML() { return this._h; }
    set innerHTML(v) {
        this._h = v;
        const gone = this.id === 'mBody' ? BODY_IDS : this.id === 'mActs' ? ACT_IDS : [];
        gone.forEach(i => delete H.els[i]);
    }
    addEventListener() {}
    focus() { H.focus.push(this.id); }
    querySelector() { return H.sheet; }
    getBoundingClientRect() { return {left: 0, top: 0, width: 100, height: 100}; }
}
H.sheet = new El('sheet');
globalThis.$ = id => H.els[id] || (H.els[id] = new El(id));
globalThis.esc = s => String(s);
globalThis.toast = (m, k) => H.toasts.push([m, k]);
globalThis.disableWithReason = (b, d, r) => { if (b) { b.disabled = !!d; b.title = d ? r : ''; } };
globalThis.loadScenarios = noop;
globalThis.document.activeElement = 'OPENER';
globalThis.document.querySelectorAll = () => [];
globalThis.document.querySelector = () => null;
// как core.js / device-modal.js
globalThis.openModal = () => { H.opens++; H.modalReturn = globalThis.document.activeElement; $('modal').classList.add('on'); };
globalThis.closeModal = () => { H.closes++; $('modal').classList.remove('on'); H.modalReturn = null; };
globalThis.Image = function () { setTimeout(() => this.onerror && this.onerror(), 0); };
const defer = key => new Promise((res, rej) => { (H.pend[key] = H.pend[key] || []).push({res, rej}); });
globalThis.api = path => defer('api:' + path);
const httpRes = (status, body) => ({ok: status < 400, status,
    headers: {get: () => 'application/json'}, json: async () => body});
// GET (repairGet) уходит в тот же 'api:'-ключ, что и api(); {__http: 404} — ответ со статусом
globalThis.fetch = (path, o) => {
    if (!o) return defer('api:' + path).then(v => v && v.__http ? httpRes(v.__http, {detail: v.detail}) : httpRes(200, v));
    H.calls.push([path, JSON.parse(o.body)]); return defer('fetch:' + path); };
H.settle = (key, v, fail) => { const d = H.pend[key].shift(); fail ? d.rej(v) : d.res(v); };
H.http = (path, status, body) => H.settle('fetch:' + path, {ok: status < 400, status,
    headers: {get: () => 'application/json'}, json: async () => body});
const tick = () => new Promise(r => setTimeout(r, 5));
const RECIPE = () => ({meta: {}, params: {}, screen_width: 1080, assets: {},
    steps: [{kind: 'click', args: {}, selector: {call: 'click', args: 'text="Войти"', fallbacks: []},
        param: null, note: 'n', texts: ['Войти'], point: [0.5, 0.5]}]});
const NODE = {id: 0, target: 0, selectors: [{call: 'click', args: 'text="Ок"', matches: 1}],
    bounds: [0.1, 0.2, 0.3, 0.4], text: 'Ок', description: '', resourceId: '', 'class': 'a.B', clickable: true};
const DUMP = () => ({screenshot: 'data:x', nodes: [NODE]});
const RK = '/api/recorder/recipe/k', SAVE = '/api/recorder/save', DECIDE = '/api/jobs/j1/decide';
const open = mode => repairOpen({mode, scenarioKey: 'k', stepIndex: 0, dumpUrl: '/dump', jobId: 'j1', title: 't'});
async function loaded(mode, recipe) {
    const p = open(mode);
    H.settle('api:' + RK, recipe || RECIPE()); H.settle('api:/dump', DUMP());
    await p; await tick();
}
async function picked(mode, recipe) {
    await loaded(mode, recipe);
    repairPick(RP.list[0], [0.2, 0.3]);
}
"""


def dom(body: str):
    return node(HARNESS + "(async () => {" + body + "})().catch(e => { console.error(e); process.exit(1); });")


def test_close_during_loading_does_not_reopen():
    got = dom("""
    const p = open('fail');
    const shownOpens = H.opens;            // скелет открыл модалку
    closeModal();                           // Escape / клик мимо / Отмена
    H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', DUMP());
    await p; await tick();
    const opens1 = H.opens, on1 = $('modal').classList.contains('on'), body1 = $('mBody').innerHTML;
    // ошибка загрузки после закрытия — тоже не открывает
    const p2 = open('fail'); closeModal();
    H.settle('api:' + RK, new Error('boom'), true); H.settle('api:/dump', DUMP());
    await p2; await tick();
    // а новое открытие после закрытия работает
    await loaded('fail');
    console.log(JSON.stringify({shownOpens, opens1, on1, skeleton: body1.includes('rp-skel'),
        opens2: H.opens, on2: $('modal').classList.contains('on'), picker: $('mBody').innerHTML.includes('rpStage')}));""")
    assert got["shownOpens"] == 1 and got["opens1"] == 1 and got["on1"] is False
    assert got["skeleton"] is True                       # ничего не перерисовано после закрытия
    assert got["opens2"] == 3 and got["on2"] is True and got["picker"] is True


def test_modal_opened_once_and_focus_return_kept():
    got = dom("""
    const p = open('fail');
    globalThis.document.activeElement = 'INSIDE_CLOSE_BTN';   // openModal сфокусировал первый элемент модалки
    H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', DUMP());
    await p; await tick();
    console.log(JSON.stringify({opens: H.opens, ret: H.modalReturn}));""")
    assert got == {"opens": 1, "ret": "OPENER"}


def test_cancel_disabled_while_saving_and_success_when_open():
    got = dom("""
    await picked('hold');
    RP.confirmed = true;
    const s = repairSubmit();
    const cancelBusy = [$('rpCancel').disabled, $('rpCancel').title];
    H.settle('api:' + RK, RECIPE()); await tick();
    H.http(SAVE, 200, {}); await tick();
    const decideSent = H.calls.filter(c => c[0] === DECIDE).length;
    H.http(DECIDE, 200, {}); await s;
    console.log(JSON.stringify({cancelBusy, decideSent, closes: H.closes, toasts: H.toasts}));""")
    assert got["cancelBusy"][0] is True and got["cancelBusy"][1]
    assert got["decideSent"] == 1 and got["closes"] == 1
    assert got["toasts"] == [["шаг исправлен, запуск повторяет его", "ok"]]


def test_closed_mid_save_saves_but_skips_decide():
    got = dom("""
    await picked('hold');
    const s = repairSubmit();
    H.settle('api:' + RK, RECIPE()); await tick();
    closeModal();                          // Escape посреди сохранения
    // чужой диалог открылся, пока летел запрос
    globalThis.openModal();
    H.http(SAVE, 200, {}); await s;
    console.log(JSON.stringify({saves: H.calls.filter(c => c[0] === SAVE).length,
        decides: H.calls.filter(c => c[0] === DECIDE).length, closes: H.closes, toasts: H.toasts,
        otherStillOpen: $('modal').classList.contains('on')}));""")
    assert got["saves"] == 1 and got["decides"] == 0
    assert got["closes"] == 1                       # только Escape; поздний finish чужой диалог не закрыл
    assert got["otherStillOpen"] is True
    assert got["toasts"] == [["шаг исправлен, но запуск его не повторил: окно закрыли раньше", "bad"]]


def test_closed_mid_decide_does_not_close_foreign_dialog():
    got = dom("""
    await picked('hold');
    const s = repairSubmit();
    H.settle('api:' + RK, RECIPE()); await tick();
    H.http(SAVE, 200, {}); await tick();
    closeModal(); globalThis.openModal();
    H.http(DECIDE, 200, {}); await s;
    console.log(JSON.stringify({closes: H.closes, on: $('modal').classList.contains('on')}));""")
    assert got == {"closes": 1, "on": True}


def test_save_error_messages_by_certainty():
    got = dom("""
    const out = [];
    for (const how of ['network', '400', '500', 'recipe']) {
        await picked('fail');
        RP.confirmed = true;
        const s = repairSubmit();
        if (how === 'recipe') H.settle('api:' + RK, new Error('нет'), true);
        else {
            H.settle('api:' + RK, RECIPE()); await tick();
            if (how === 'network') H.settle('fetch:' + SAVE, new TypeError('Failed to fetch'), true);
            else H.http(SAVE, Number(how), {detail: 'плохо'});
        }
        await s; await tick();
        out.push($('rpStatus').textContent);
    }
    console.log(JSON.stringify(out));""")
    assert got[0].endswith("Неизвестно, записалось ли изменение — откройте сценарий и проверьте.")
    assert got[1].endswith("Файл не изменён.") and "плохо" in got[1]
    assert got[2].endswith("Неизвестно, записалось ли изменение — откройте сценарий и проверьте.")
    assert got[3].endswith("Файл не изменён.")


def test_hold_on_plain_click_shows_message_in_picker_load():
    got = dom("""
    const r = RECIPE(); delete r.steps[0].texts; delete r.steps[0].point;
    await loaded('hold', r);
    console.log(JSON.stringify($('mBody').innerHTML));""")
    assert "нажатие записано по описанию элемента" in got and "нельзя починить кликом:" not in got


def test_keyboard_and_mouse_pick_same_element_and_no_duplicates():
    got = dom("""
    const parent = {id: 0, target: 0, selectors: [{call: 'click', args: 'text="Ок"', matches: 1}],
        bounds: [0.1, 0.2, 0.5, 0.6], text: 'Ок', description: '', resourceId: '', 'class': 'a.B', clickable: true};
    const child = {id: 1, target: 0, selectors: [], bounds: [0.2, 0.3, 0.3, 0.4], text: 'Ок', description: '',
        resourceId: '', 'class': 'a.T', clickable: false};
    const dump = {screenshot: 'data:x', nodes: [parent, child]};
    const p = open('fail');
    H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', dump);
    await p; await tick();
    const listLen = RP.list.length;
    const hit = recHit(0.25, 0.35, dump);                       // мышь: по ребёнку
    repairPick(dump.nodes[hit.target], [0.25, 0.35]);
    const mouse = JSON.stringify(Object.assign({}, RP.built, {point: null}));
    RP.built = null;
    repairHover(0); repairKey({key: 'Enter', preventDefault: noop});   // клавиатура
    const kbd = JSON.stringify(Object.assign({}, RP.built, {point: null}));
    console.log(JSON.stringify({listLen, same: mouse === kbd, bounds: RP.built.bounds}));""")
    assert got["listLen"] == 1 and got["same"] is True and got["bounds"] == [0.1, 0.2, 0.5, 0.6]


def test_hover_label_written_only_on_change_and_hint_visible():
    got = dom("""
    await picked('fail');
    let writes = 0, v = '';
    const el = $('rpHover');
    Object.defineProperty(el, 'textContent', {get: () => v, set: x => { writes++; v = x; }});
    repairHover(0); repairHover(0); repairHover(0); repairHover(-1);
    console.log(JSON.stringify({writes, hint: $('mBody').innerHTML.includes('rp-hint')}));""")
    assert got == {"writes": 2, "hint": True}


def test_hold_reason_no_double_period_and_toast_casing():
    got = dom("""
    await picked('hold');
    RP.confirmed = true;
    const s = repairSubmit();
    const plain = RECIPE(); delete plain.steps[0].texts; delete plain.steps[0].point;
    H.settle('api:' + RK, plain); await s; await tick();
    const full = $('rpStatus').textContent;
    await picked('fail');
    RP.confirmed = true;
    const s2 = repairSubmit();
    const tap = RECIPE(); tap.steps[0] = {kind: 'tap', args: {x: 0.1, y: 0.2}, selector: null, param: null, note: ''};
    H.settle('api:' + RK, tap); await s2; await tick();
    console.log(JSON.stringify([full, $('rpStatus').textContent]));""")
    assert ".." not in got[0] and got[0].endswith(". Файл не изменён.")
    assert got[0].startswith("Запуск ждёт на шаге")
    assert got[1].startswith("Шаг больше нельзя починить: ") and ".." not in got[1]


def test_on_done_not_leaked_to_next_dialog():
    got = dom("""
    const fired = [];
    await loaded('fail');
    RP.opts.onDone = () => fired.push('A');
    repairPick(RP.list[0], [0.2, 0.3]); RP.confirmed = true;
    const s = repairSubmit();
    H.settle('api:' + RK, RECIPE()); await tick();
    closeModal();                                   // закрыли посреди сохранения
    const p = repairOpen({mode: 'fail', scenarioKey: 'k', stepIndex: 0, dumpUrl: '/dump', title: 't',
        onDone: () => fired.push('B')});
    H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', DUMP()); await p; await tick();
    H.http(SAVE, 200, {}); await s; await tick();
    console.log(JSON.stringify(fired));""")
    assert got == ["A"]


def test_hint_says_choose_and_arrow_from_nothing_hits_last():
    got = dom("""
    const nodes = [0, 1, 2].map(i => ({id: i, target: i, selectors: [{call: 'click', args: 'text="a' + i + '"', matches: 1}],
        bounds: [0.1, 0.1 + i * 0.2, 0.3, 0.2 + i * 0.2], text: 'a' + i, description: '', resourceId: '',
        'class': 'a.B', clickable: true}));
    const p = open('fail');
    H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', {screenshot: 'data:x', nodes}); await p; await tick();
    const hint = $('mBody').innerHTML;
    const key = k => repairKey({key: k, preventDefault: noop});
    const seq = [];
    repairHover(-1); key('ArrowLeft'); seq.push(RP.hover);
    repairHover(-1); key('ArrowUp'); seq.push(RP.hover);
    repairHover(-1); key('ArrowRight'); seq.push(RP.hover);
    repairHover(0); key('ArrowLeft'); seq.push(RP.hover);
    console.log(JSON.stringify({seq, ok: hint.includes('Enter — выбрать'), bad: hint.includes('подтвердить')}));""")
    assert got == {"seq": [2, 2, 0, 2], "ok": True, "bad": False}


def test_focus_lands_on_stable_controls():
    got = dom("""
    const p = open('fail');
    const skel = H.focus.slice(); H.focus.length = 0;
    H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', DUMP()); await p; await tick();
    const picker = H.focus.slice(); H.focus.length = 0;
    // сообщение: с «Повторить» и без
    const p2 = open('fail');
    H.settle('api:' + RK, new Error('boom'), true); H.settle('api:/dump', DUMP()); await p2; await tick();
    const withRetry = H.focus.slice(); H.focus.length = 0;
    const p3 = repairOpen({mode: 'nope'}); await p3;
    const noRetry = H.focus.slice(); H.focus.length = 0;
    // busy: фокус уходит с кнопки до её отключения; после — на «Сохранить»
    await picked('fail'); H.focus.length = 0;
    RP.confirmed = true;
    repairBusy(true, 'x');
    const busyOn = H.focus.slice(); H.focus.length = 0;
    repairBusy(false);
    const busyOff = H.focus.slice();
    console.log(JSON.stringify({skel, picker, withRetry, noRetry, busyOn, busyOff}));""")
    assert got["skel"][-1] == "rpCancel" and got["picker"][-1] == "rpStage"
    assert got["withRetry"][-1] == "rpRetry" and got["noRetry"][-1] == "rpClose"
    assert got["busyOn"] == ["rpStage"] and got["busyOff"][-1] == "rpSave"


def test_no_retry_on_404_load_but_retry_on_other_errors():
    got = dom("""
    const out = [];
    for (const st of [404, 500]) {
        const p = open('fail');
        H.settle('api:' + RK, RECIPE()); H.settle('api:/dump', {__http: st, detail: 'нет снимка'});
        await p; await tick();
        out.push([$('mBody').innerHTML.includes('нет снимка'), $('mActs').innerHTML.includes('rpRetry'),
                  $('mTitle').textContent]);
        closeModal();
    }
    console.log(JSON.stringify(out));""")
    assert got[0][0] and got[0][1] is False
    assert got[1][0] and got[1][1] is True
    assert got[0][2] == "Починка шага 1"          # короткий заголовок, не текст ошибки


def test_hold_decide_network_failure_says_outcome_unknown():
    got = dom("""
    await picked('hold'); RP.confirmed = true;
    const s = repairSubmit();
    H.settle('api:' + RK, RECIPE()); await tick();
    H.http(SAVE, 200, {}); await tick();
    H.settle('fetch:' + DECIDE, new TypeError('Failed to fetch'), true); await s;
    const net = H.toasts.slice(); H.toasts.length = 0;
    await picked('hold'); RP.confirmed = true;
    const s2 = repairSubmit();
    H.settle('api:' + RK, RECIPE()); await tick();
    H.http(SAVE, 200, {}); await tick();
    H.http(DECIDE, 409, {detail: 'занято'}); await s2;
    console.log(JSON.stringify([net, H.toasts]));""")
    net, http = got
    assert net[0][0] == "шаг исправлен; повторил ли его запуск, неизвестно — проверьте в «Запусках»"
    assert "занято" in http[0][0] and http[0][0].startswith("шаг исправлен в сценарии, но запуск его не повторил")


def test_decide_без_цели_при_пустом_патче_и_text_только_при_другой_части():
    got = node("""
    const steps = [
        {selector: {call: 'click', args: '???'}, point: [2, 0]},        // пусто
        {},
        {selector: {call: 'click', args: 'text="x"'}},                   // sel без текстов
        {point: [0.1, 0.2]},                                             // at без текстов
        {texts: ['Войти']},                                              // только тексты
        {selector: {call: 'click', args: 'text="x"'}, texts: ['a'], point: [0.5, 0.5]}];
    console.log(JSON.stringify(steps.map(s => [repairPatchFromStep(s), repairDecideBody(s)])));""")
    for i in (0, 1):
        patch, body = got[i]
        assert patch == {} and body == {"decision": "retry"}     # target не шлётся
    assert got[2][0] == {"sel": [{"text": "x"}], "text": []}     # стирает старые тексты
    assert got[3][0] == {"at": [0.1, 0.2], "text": []}
    assert got[4][0] == {"text": ["Войти"]}
    assert got[5][0]["text"] == ["a"]
    for patch, body in got:
        if patch:
            assert body == {"decision": "retry", "target": patch}
            assert normalize_target(patch) == patch              # как на сервере
        # пустой патч на сервер как цель не уходит; вида {"text": []} не бывает
        assert patch != {"text": []}
