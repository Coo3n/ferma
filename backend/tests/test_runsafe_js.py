"""Безопасный массовый запуск: пробный телефон, «перезапустить упавшие», «где встал»."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {window: {}, t: (k, v) => k + (v ? ' ' + JSON.stringify(v) : ''), esc: s => String(s)};
vm.createContext(ctx);
for (const f of process.argv.slice(1)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx);
vm.runInContext('window.jobWhereStopped = jobWhereStopped; this.h={rdTrialPlan,rdTrialView,rdTrialBarHtml,rdTrialPending,rerunFailedPlan,jobWhereStopped}', ctx);
const h = ctx.h;
const plain = v => JSON.parse(JSON.stringify(v));

// пробный: один телефон — пробовать не на ком
assert.strictEqual(h.rdTrialPlan(['a'], []), null);
assert.strictEqual(h.rdTrialPlan([], []), null);
// первым — свободный, остальные по порядку
assert.deepStrictEqual(plain(h.rdTrialPlan(['a', 'b', 'c'], [{serial: 'a', busy_job: 'x'}])),
    {first: 'b', rest: ['a', 'c']});
assert.deepStrictEqual(plain(h.rdTrialPlan(['a', 'b'], [])), {first: 'a', rest: ['b']});
// все заняты — первый выбранный
assert.deepStrictEqual(plain(h.rdTrialPlan(['a', 'b'], [{serial: 'a', busy_job: 1}, {serial: 'b', busy_job: 2}])),
    {first: 'a', rest: ['b']});

// полоса пробы — по состоянию с сервера
const tr = (state, extra) => Object.assign({state, job: 'j1', serial: 'a', device_name: 'Phone 3',
    job_status: 'running', rest: 9, started: 0, skipped: 0, error: ''}, extra || {});
let v = h.rdTrialView(tr('running'), {id: 'j1', status: 'running', step_index: 1, step_total: 5});
assert.strictEqual(v.title, 'run.proba_na {"name":"Phone 3"}');
assert.strictEqual(v.now, 'run.proba_shag {"n":2,"total":5}');
assert.deepStrictEqual(plain(v.acts), ['drop']);
assert.strictEqual(h.rdTrialView(tr('running', {job_status: 'held'}), null).tone, 'warn');
v = h.rdTrialView(tr('failed', {job_status: 'failed'}), {id: 'j1', status: 'failed', step_index: 2, error_info: {title: 'нет кнопки'}});
assert.strictEqual(v.tone, 'bad');
assert.strictEqual(v.title, 'run.proba_ne_proshla_bar {"name":"Phone 3","n":9}');
assert.deepStrictEqual(plain(v.acts), ['release', 'drop']);
assert.ok(v.now.includes('нет кнопки'));
v = h.rdTrialView(tr('started', {job_status: 'passed', started: 7, skipped: 2}), null);
assert.strictEqual(v.title, 'run.proba_proshla_bar {"name":"Phone 3","n":7}');
assert.deepStrictEqual(plain(v.acts), []);
assert.deepStrictEqual(plain(v.note), ['run.propuscheny_ne_v_seti {"n":2}']);
assert.strictEqual(h.rdTrialView(null), null);
for (const [st, pending] of [['running', true], ['failed', true], ['started', false],
        ['forced', false], ['dropped', false]])
    assert.strictEqual(h.rdTrialPending(tr(st)), pending, st);
assert.strictEqual(h.rdTrialPending(undefined), false);
// кнопки — только там, где решение ещё нужно
const bar = h.rdTrialBarHtml([{id: 'j1', batch: 'b1', status: 'failed', trial: tr('failed')}]);
assert.ok(bar.includes("rdTrialRelease('b1'") && bar.includes("rdTrialDrop('b1'"));
assert.ok(!h.rdTrialBarHtml([{id: 'j1', batch: 'b1', status: 'passed', trial: tr('started')}]).includes('<button'));
assert.strictEqual(h.rdTrialBarHtml([{id: 'j1', batch: 'b1', status: 'passed'}]), '');

// перезапуск: только упавшие, телефон один раз, те же параметры
assert.strictEqual(h.rerunFailedPlan([{status: 'passed', serial: 'a'}]), null);
assert.strictEqual(h.rerunFailedPlan([]), null);
assert.deepStrictEqual(plain(h.rerunFailedPlan([
    {status: 'passed', serial: 'a', scenario_key: 'vk', params: {n: 1}},
    {status: 'failed', serial: 'b', scenario_key: 'vk', params: {n: 1}},
    {status: 'failed', serial: 'b', scenario_key: 'vk', params: {n: 1}},
    {status: 'cancelled', serial: 'c', scenario_key: 'vk', params: {n: 1}},
    {status: 'failed', serial: 'd', scenario_key: 'vk', params: {n: 1}},
])), {scenario: 'vk', params: {n: 1}, serials: ['b', 'd']});

// где встал
assert.strictEqual(h.jobWhereStopped({status: 'passed', step_index: 3}), '');
assert.strictEqual(h.jobWhereStopped(null), '');
assert.strictEqual(h.jobWhereStopped({status: 'failed', step_index: 3, error_info: {title: 'нет кнопки'}}),
    'jobs.vstal_na_shage {"n":4,"why":"нет кнопки"}');
assert.strictEqual(h.jobWhereStopped({status: 'failed', step_index: 0}), 'jobs.vstal_na_shage_bez {"n":1}');
assert.strictEqual(h.jobWhereStopped({status: 'failed', step_index: -1, error: 'упал'}), 'упал');
assert.strictEqual(h.jobWhereStopped({status: 'failed', step_index: -1}), '');
"""


def test_runsafe_helpers():
    node = require_node()
    res = subprocess.run([node, "-e", SCRIPT, str(JS / "rundialog.js"), str(JS / "jobs.js")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

