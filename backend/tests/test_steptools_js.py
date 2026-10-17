"""Чистые помощники steptools.js (история, дифф, превью жеста) — в node без браузера."""
import subprocess
from pathlib import Path

from _node import require_node

ROOT = Path(__file__).resolve().parents[2] / "frontend" / "js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const esc = v => String(v ?? '').replace(/[&<>"]/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const els = {};
const doc = {addEventListener() {}, querySelectorAll: () => [], getElementById: () => null,
             createElement: () => ({style: {}})};
const toasts = [];
const REC = {steps: [], params: {}, nextId: 100, sel: new Set(), open: null, edit: null};
const saved = [];
const ctx = {esc, S: {view: 'device'}, REC, document: doc, window: {}, console,
    toast: m => toasts.push(m), $: id => els[id] || null,
    recSave() { saved.push(JSON.stringify(REC.steps.length)); },
    recRender() {}, recSync() {}, editScenario: async () => {},
    recFind: id => REC.steps.find(s => s.id === Number(id)),
    recLabel: s => s.kind + (s.args && s.args.value ? ':' + s.args.value : ''),
    recFallbacks: s => (s.alts || []).map(a => a.args).filter(a => a !== s.selector.args),
    recCode: s => 'ctx.' + s.kind + '()', recPrune() {}, disableWithReason() {},
    recIcon: () => '', t: key => key, isActive: s => ['queued', 'running', 'held'].includes(s),
    JOB_DECISIONS: [], recPayload: () => ({steps: []}), recMeta: () => ({}),
    recSubmit: async () => {}, recModeOff: () => {}, recTeachSubmit: async () => {}};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8')
    + ';this.h={stLcs,stDiffSteps,stGestureSvg,stHist,stHistNote,stHistReset,recUndo,recRedo,'
    + 'recDup,recSelToggle,recSelOptional,recSelPause,recSelDelete,recSelBar,recBadges,'
    + 'recFlexEditor,recSetFlex,jobStepsHtml,jobProgressHtml,stSig}', ctx);
const h = ctx.h;
const J = x => JSON.parse(JSON.stringify(x));
const step = (id, kind, args = {}, extra = {}) => ({id, kind, args, param: null, note: '', ...extra});

// --- LCS и дифф
assert.deepStrictEqual(JSON.parse(JSON.stringify(h.stLcs(['a', 'b', 'c'], ['a', 'c']))),
    [{t: 'same', a: 0, b: 0}, {t: 'del', a: 1}, {t: 'same', a: 2, b: 1}]);
const A = [step(1, 'key', {name: 'home'}), step(2, 'type', {value: 'a'}), step(3, 'sleep', {seconds: 1})];
const B = [step(1, 'key', {name: 'home'}), step(2, 'type', {value: 'b'}), step(4, 'tap', {x: 0.1, y: 0.2})];
const d = h.stDiffSteps(A, B, ctx.recLabel);
assert.deepStrictEqual(J(d.map(x => x.kind)), ['chg', 'del', 'add']);
assert(d[0].details[0].includes('«a» → «b»'), d[0].details[0]);
assert.strictEqual(h.stDiffSteps(A, A, ctx.recLabel).length, 0);
const flexChg = h.stDiffSteps([step(1, 'key', {name: 'a'})],
    [step(1, 'key', {name: 'a'}, {optional: true, retries: 2})], ctx.recLabel);
assert(flexChg[0].details.some(t => t.includes('необязательным')));
assert(flexChg[0].details.some(t => t.includes('повторов')));

// --- превью жеста
assert(h.stGestureSvg(step(1, 'swipe', {x1: .5, y1: .8, x2: .5, y2: .2, duration: .3}), 400, 800).includes('g-line'));
assert(h.stGestureSvg(step(1, 'tap', {x: .5, y: .5}), 400, 800).includes('g-ring'));
assert(h.stGestureSvg(step(1, 'long_tap', {x: .5, y: .5}), 400, 800).includes('long'));
assert.strictEqual(h.stGestureSvg(step(1, 'sleep', {seconds: 1}), 400, 800), '');
assert.strictEqual(h.stGestureSvg(step(1, 'swipe', {x1: 'a'}), 400, 800), '');

// --- история: отмена, возврат, слияние быстрых правок
REC.steps = [step(1, 'key', {name: 'home'})];
h.stHistReset();
REC.steps.push(step(2, 'key', {name: 'back'}));
h.stHistNote();
assert.strictEqual(h.stHist.undo.length, 1);
h.recUndo();
assert.deepStrictEqual(J(REC.steps.map(s => s.id)), [1]);
h.recRedo();
assert.deepStrictEqual(J(REC.steps.map(s => s.id)), [1, 2]);
// быстрые правки одного шага — одна запись отмены
h.stHist.at = Date.now();
REC.steps[1].args.name = 'b'; h.stHistNote();
REC.steps[1].args.name = 'ba'; h.stHistNote();
assert.strictEqual(h.stHist.undo.length, 1, 'правки внутри окна сливаются');
// без изменений — не пишем
const n = h.stHist.undo.length; h.stHistNote(); assert.strictEqual(h.stHist.undo.length, n);

// --- дубль и группа
REC.steps = [step(1, 'key', {name: 'a'}), step(2, 'sleep', {seconds: 1})];
h.stHistReset();
h.recDup(1);
assert.deepStrictEqual(J(REC.steps.map(s => s.kind)), ['key', 'key', 'sleep']);
assert.notStrictEqual(REC.steps[1].id, 1);
assert.notStrictEqual(REC.steps[1], REC.steps[0]);
REC.steps = [step(1, 'key', {name: 'a'}), step(2, 'sleep', {seconds: 1}), step(3, 'tap', {x: 0, y: 0})];
REC.sel = new Set([1, 2, 3]);
h.recSelOptional();
assert.deepStrictEqual(J(REC.steps.map(s => !!s.optional)), [true, false, true], 'sleep не гибкий');
h.recSelOptional();
assert.deepStrictEqual(J(REC.steps.map(s => !!s.optional)), [false, false, false], 'второй вызов снимает');
els.selPause = {value: '2'};
REC.sel = new Set([1]);
h.recSelPause();
assert.deepStrictEqual(J(REC.steps.map(s => s.kind)), ['key', 'sleep', 'sleep', 'tap']);
assert.strictEqual(REC.steps[1].args.seconds, 2);
REC.sel = new Set([1, 2]); h.recSelDelete();
assert.deepStrictEqual(J(REC.steps.map(s => s.kind)), ['sleep', 'tap']);
assert.strictEqual(h.recSelBar(), '');
REC.sel = new Set([2]); assert(h.recSelBar().includes('<b>1</b> выбрано'));

// --- гибкость шага
const k = step(9, 'key', {name: 'b'}, {optional: true, retries: 2});
assert(h.recBadges(k).includes('можно пропустить') && h.recBadges(k).includes('↻2'));
assert.strictEqual(h.recBadges(step(1, 'key')), '');
assert.strictEqual(h.recFlexEditor(step(1, 'sleep', {seconds: 1})), '');
assert(h.recFlexEditor(k).includes('selected'));
REC.steps = [step(5, 'sleep', {seconds: 1}), k];
h.recSetFlex(5, 'optional', true);
assert(!REC.steps[0].optional, 'sleep нельзя сделать необязательным');
h.recSetFlex(9, 'retries', '9');
assert.strictEqual(REC.steps[1].retries, 5);

// --- журнал задач
assert.strictEqual(h.jobStepsHtml({}), '');
const html = h.jobStepsHtml({timeline: [{i: 0, status: 'ok', label: '<x>'}, {i: 1, status: 'failed', secs: 2}],
    error_info: {title: 'Не то', hint: 'Смотрите кадр', timeout: true}, start_step: 2, speed: 0.5});
assert(html.includes('jchip failed') && html.includes('Не дождались') && html.includes('с шага 3'));
assert(html.includes('замедление') && html.includes('&lt;x&gt;'));
assert(h.jobProgressHtml({status: 'running', step_index: 1, step_total: 5}).includes('2/5'));
assert.strictEqual(h.jobProgressHtml({status: 'passed', step_total: 5}), '');
console.log('ok');
"""


def test_steptools_helpers():
    node = require_node()
    result = subprocess.run([node, "-e", SCRIPT, str(ROOT / "steptools.js")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "ok"
