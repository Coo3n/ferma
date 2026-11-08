"""ИИ-мастер (ai-wizard.js): чистая логика правок, устаревших ответов и состояний."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "ai-wizard.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `;this.f={aiApplyFix,aiFindingValid,
  aiShiftFindings,aiAccept,aiRunBadge,aiGroupObs,aiProgress,aiVisionText,aiRiskyText,aiStepLabel,aiIsActive}`, ctx);
const f = ctx.f;
const J = x => JSON.parse(JSON.stringify(x));
const S = (...k) => k.map(kind => ({kind, args: {}}));

// --- одна правка
let r = f.aiApplyFix(S('a', 'b', 'c'), {op: 'delete', index: 1});
assert.deepStrictEqual(J(r.steps).map(s => s.kind), ['a', 'c']);
r = f.aiApplyFix(S('a', 'b'), {op: 'replace', index: 0, step: {kind: 'x', args: {}}});
assert.deepStrictEqual(J(r.steps).map(s => s.kind), ['x', 'b']);
r = f.aiApplyFix(S('a', 'b'), {op: 'insert', index: 1, step: {kind: 'n', args: {}}});
assert.deepStrictEqual(J(r.steps).map(s => s.kind), ['a', 'n', 'b']);
r = f.aiApplyFix(S('a'), {op: 'insert', index: 1, step: {kind: 'n', args: {}}});   // в конец
assert.strictEqual(r.steps.length, 2);
const orig = S('a', 'b'); f.aiApplyFix(orig, {op: 'delete', index: 0});
assert.strictEqual(orig.length, 2);                                                // вход не мутирован
for (const bad of [{op: 'delete', index: 2}, {op: 'delete', index: -1}, {op: 'replace', index: 0},
                   {op: 'insert', index: 3, step: {kind: 'n'}}, {op: 'zap', index: 0}, null, {op: 'delete'}])
    assert.ok(f.aiApplyFix(S('a', 'b'), bad).error, JSON.stringify(bad));

// --- валидность замечания
const fnd = (steps, fix) => ({id: 'f', title: 't', steps, fix});
assert.ok(f.aiFindingValid(fnd([0], null), 2));
assert.ok(!f.aiFindingValid(fnd([], null), 2));
assert.ok(!f.aiFindingValid(fnd([2], null), 2));
assert.ok(!f.aiFindingValid(fnd([0], {op: 'delete', index: 2}), 2));
assert.ok(f.aiFindingValid(fnd([0], {op: 'insert', index: 2, step: {kind: 'k'}}), 2));

// --- сдвиг остальных замечаний после правки
const list = [{id: 'a', steps: [0], fix: {op: 'delete', index: 0}, state: 'pending'},
              {id: 'b', steps: [2], fix: {op: 'replace', index: 2, step: {kind: 'x'}}, state: 'pending'},
              {id: 'c', steps: [0], fix: null, state: 'pending'}];
let sh = J(f.aiShiftFindings(list, {op: 'delete', index: 0}, 'a'));
assert.strictEqual(sh[1].steps[0], 1);            // после удаления шаг 2 стал шагом 1
assert.strictEqual(sh[1].fix.index, 1);
assert.strictEqual(sh[2].state, 'stale');         // трогало удалённый шаг
sh = J(f.aiShiftFindings(list, {op: 'insert', index: 1, step: {kind: 'n'}}, 'zz'));
assert.strictEqual(sh[1].steps[0], 3);            // вставка раньше — индекс вырос
assert.strictEqual(sh[0].steps[0], 0);

// --- устаревшие ответы
const cur = {req: {review: 2}, editSeq: 5};
assert.ok(f.aiAccept(cur, {ch: 'review', n: 2, seq: 5, version: 'v1'}, {version: 'v1'}));
assert.ok(!f.aiAccept(cur, {ch: 'review', n: 1, seq: 5}, {}), 'поздний ответ');
assert.ok(!f.aiAccept(cur, {ch: 'review', n: 2, seq: 4}, {}), 'шаги менялись');
assert.ok(!f.aiAccept(cur, {ch: 'review', n: 2, seq: 5, version: 'v1'}, {version: 'v2'}), 'другая версия');
assert.ok(!f.aiAccept(cur, {ch: 'review', n: 2, seq: 5, request_id: 'a'}, {request_id: 'b'}));
assert.ok(f.aiAccept(cur, {ch: 'review', n: 2, seq: 5, version: 'v1'}, {}), 'версии нет в ответе');
assert.ok(!f.aiAccept(cur, {ch: 'draft', n: 1}, {}), 'канал без запросов');

// --- шапка: актуальность проверки
assert.strictEqual(f.aiRunBadge([], false, false).kind, 'none');
assert.strictEqual(f.aiRunBadge([], false, true).kind, 'need');
assert.strictEqual(f.aiRunBadge([{is_current: true}], false, true).kind, 'ok');
assert.strictEqual(f.aiRunBadge([{is_current: true}], true, true).text, 'Нужна новая проверка');   // любая правка
assert.strictEqual(f.aiRunBadge([{is_current: false}], false, true).text, 'Нужна новая проверка');
// остановленная или упавшая проверка ничего не подтверждает
assert.strictEqual(f.aiRunBadge([{is_current: true, status: 'cancelled'}], false, true).kind, 'need');
assert.strictEqual(f.aiRunBadge([{is_current: true, status: 'failed'}], false, true).kind, 'bad');
assert.strictEqual(f.aiRunBadge([{is_current: true, status: 'passed'}], false, true).kind, 'ok');

// --- анализ: три группы, неизвестная основа = «не проверено»
const g = J(f.aiGroupObs([{text: 'a', basis: 'confirmed'}, {text: 'b', basis: 'probable'},
                          {text: 'c', basis: 'wow'}, {text: '', basis: 'confirmed'}, null]));
assert.deepStrictEqual([g.confirmed.length, g.probable.length, g.unverified.length], [1, 1, 1]);
assert.ok(/не понимает/.test(f.aiVisionText('no')));
assert.ok(/не удалось/.test(f.aiVisionText('unknown')));
assert.ok(/понимает/.test(f.aiVisionText('yes')));

// --- прогресс: процент только настоящий
assert.strictEqual(f.aiProgress({state: 'running', stage: 'pulling', percent: null}).kind, 'indeterminate');
assert.strictEqual(f.aiProgress({state: 'running', stage: 'pulling', percent: 41.6}).kind, 'real');
assert.strictEqual(f.aiProgress({state: 'running', stage: 'pulling'}).kind, 'indeterminate');
assert.strictEqual(f.aiProgress({state: 'error', error: 'нет места'}).text, 'нет места');
assert.strictEqual(f.aiProgress({state: 'cancelled'}).kind, 'cancelled');

// --- прочее
assert.deepStrictEqual(J(f.aiRiskyText([{index: 2, reason: 'оплата'}])), ['Шаг 3: оплата']);
assert.ok(f.aiIsActive('running') && f.aiIsActive('held') && !f.aiIsActive('passed') && !f.aiIsActive('failed'));
assert.strictEqual(f.aiStepLabel({kind: 'type', args: {text: 'привет'}}), 'Ввести текст «привет»');
assert.strictEqual(f.aiStepLabel({kind: 'zzz', args: {}}), 'zzz');
"""


def test_ai_wizard_logic():
    node = require_node()
    res = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, res.stderr
