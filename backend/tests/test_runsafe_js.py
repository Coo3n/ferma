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
vm.runInContext('this.h={rdTrialPlan,rdTrialStage,rerunFailedPlan,jobWhereStopped}', ctx);
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

for (const [st, stage] of [['passed', 'ok'], ['failed', 'fail'], ['cancelled', 'fail'],
        ['held', 'held'], ['queued', 'run'], ['running', 'run'], ['cancelling', 'run']])
    assert.strictEqual(h.rdTrialStage(st), stage, st);

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


RACE = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const posts = [];
let release;
const gate = new Promise(r => { release = r; });
const ctx = {window: {}, t: k => k, esc: s => String(s), toast: () => {},
    S: {devices: [{serial: 'a', online: true}, {serial: 'b', online: true}], hidden: new Set(), view: 'fleet'},
    api: async () => { await gate; return [{id: 'j1', status: 'passed'}]; },
    post: async (url, body) => { posts.push(body); return {}; },
    setInterval: () => 1, clearInterval: () => {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
vm.runInContext(`RD_TRIALS.set('b1', {batch: 'b1', job: 'j1', first: 'a', rest: ['b'],
    scenario: 'vk', params: {}, repeat: 1, stage: 'run'});`, ctx);
(async () => {
    // два тика разом — сеть медленнее интервала опроса
    const one = vm.runInContext('rdTrialTick()', ctx);
    const two = vm.runInContext('rdTrialTick()', ctx);
    release();
    await Promise.all([one, two]);
    assert.strictEqual(posts.length, 1, 'остальные запущены ' + posts.length + ' раз');
})().catch(e => { console.error(e); process.exit(1); });
"""


def test_пробный_не_запускает_остальных_дважды():
    node = require_node()
    res = subprocess.run([node, "-e", RACE, str(JS / "rundialog.js")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
