"""Чистые помощники deviations.js проверяются в node без браузера."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "deviations.js"
JOBS_JS = JS.parent / "jobs.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const esc = v => String(v ?? '').replace(/[&<>"]/g,
    c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const toasts = [];
const ctx = {esc, S: {}, $: () => null, document: {}, window: {}, console,
             toast: (m, k) => toasts.push([m, k])};
vm.createContext(ctx);
vm.runInContext('let modalReturn = null;', ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8')
    + ';this.h={deviationShotUrl,parseMiss,missPoint,deviationShotBody,deviationRepairMode,deviationRepairFail,deviationRepairHold,deviationRepairButton,holdActions,repointModalReturn,deviationCard,setModalReturn:v=>{modalReturn=v},getModalReturn:()=>modalReturn}', ctx);
const h = ctx.h;

assert.strictEqual(h.deviationShotUrl({job_id: 'a/b', shot: 'x y.png'}),
    '/api/jobs/a%2Fb/artifacts/x%20y.png');
for (const bad of ['', 'garbage', '[]', '5', 'null'])
    assert.strictEqual(Object.keys(h.parseMiss({miss: bad})).length, 0, bad);
assert.deepStrictEqual(JSON.parse(JSON.stringify(h.parseMiss({miss: '{"at":[0.1,0.2]}'}))),
    {at: [0.1, 0.2]});
for (const bad of [{}, {at: [1.2, 0.5]}, {at: [-0.1, 0]}, {at: [NaN, 0]},
                   {at: ['0.5', '0.5']}, {at: [0.5]}, {at: 'ab'}])
    assert.strictEqual(h.missPoint(bad), null, JSON.stringify(bad));
const p = h.missPoint({at: [0.25, 0.7]});
assert.strictEqual(p.x, 0.25); assert.strictEqual(p.y, 0.7);

const item = {job_id: 'j1', shot: 's.png', title: '<b>x</b>', devices: ['d1'],
              scenario_name: 'sc', step_index: 2};
const ok = h.deviationShotBody(item, {at: [0.25, 0.7], sel: [{id: 'a'}], text: ['Ok']});
assert(ok.includes('left:25%')); assert(ok.includes('ожидали здесь'));
assert(ok.includes('«3»')); assert(ok.includes('<code'));
assert(!ok.includes('<b>x</b>')); assert(ok.includes('&lt;b&gt;x&lt;/b&gt;'));
const no = h.deviationShotBody({...item, step_index: -1}, {at: [2, 2]});
assert(!no.includes('left:')); assert(!no.includes('ожидали здесь'));
assert(!no.includes('шаг'));
// --- маркер у верхнего края
assert(h.deviationShotBody(item, {at: [0.3, 0.05]}).includes(' below'));
assert(!h.deviationShotBody(item, {at: [0.3, 0.1]}).includes(' below'));
assert(!h.deviationShotBody(item, {at: [0.3, 0.5]}).includes(' below'));

// --- режим починки
const fail = {id: 'ab12', kind: 'fail', step_index: 0, job_id: 'j1', shot: 's.png',
              scenario_key: 'k', title: 'a"b<i>', miss: '{"at":[0.5,0.5]}'};
const M = h.deviationRepairMode;
assert.strictEqual(M(fail), 'fail');
for (const drop of ['step_index', 'job_id', 'shot', 'scenario_key'])
    assert.strictEqual(M({...fail, [drop]: drop === 'step_index' ? -1 : ''}), null, drop);
assert.strictEqual(M({...fail, step_index: undefined}), null);
for (const kind of ['escape', 'branch', 'layer'])
    assert.strictEqual(M({...fail, kind}), null, kind);
const hold = {...fail, id: 'cd34', kind: 'hold', shot: ''};
assert.strictEqual(M(hold), 'hold');
assert.strictEqual(M({...hold, scenario_key: ''}), null);
assert.strictEqual(M({...hold, step_index: -1}), null);
assert.strictEqual(M(null), null);

// --- разметка
assert(h.deviationRepairButton(fail).includes('Починить шаг'));
assert(h.deviationRepairButton(fail).includes('#i-wrench'));
assert.strictEqual(h.deviationRepairButton({...fail, shot: ''}), '');
ctx.findDeviation = id => [fail, hold].find(x => x.id === id);
const failCard = h.deviationCard(fail);
assert(failCard.includes('Починить шаг'));
assert(!failCard.includes('a"b')); assert(failCard.includes('a&quot;b'));
assert(!h.deviationCard({...fail, step_index: -1}).includes('Починить шаг'));

// --- клик: fail
let got = null;
ctx.repairOpen = a => { got = a; };
h.deviationRepairFail('ab12');
assert.strictEqual(typeof got.onDone, 'function');
const {onDone, ...rest} = got;
assert.deepStrictEqual(JSON.parse(JSON.stringify(rest)), {
    mode: 'fail', scenarioKey: 'k', stepIndex: 0,
    dumpUrl: '/api/deviations/ab12/dump', miss: {at: [0.5, 0.5]}, title: 'a"b<i>'});
let seen = null;
ctx.deviationSeen = id => { seen = id; };
onDone(); assert.strictEqual(seen, 'ab12');
delete ctx.repairOpen; toasts.length = 0; got = null;
h.deviationRepairFail('ab12');
assert.strictEqual(got, null); assert.strictEqual(toasts.length, 1);
assert(toasts[0][0].includes('обновите страницу')); assert.strictEqual(toasts[0][1], 'bad');

// --- клик: hold
ctx.repairOpen = a => { got = a; };
ctx.S.jobs = [{id: 'j1', serial: 'a/b c', status: 'held', repairable: true}];
h.deviationRepairHold('cd34');
assert.strictEqual(got.mode, 'hold'); assert.strictEqual(got.jobId, 'j1');
assert.strictEqual(got.dumpUrl, '/api/devices/a%2Fb%20c/inspect');
assert.strictEqual(got.stepIndex, 0); assert.strictEqual(got.scenarioKey, 'k');
const hh = h.holdActions(hold);
// главное — указать на скрине; остальное мелким «или:», «уронить» последним
assert(hh.includes('Указать на снимке, куда нажать'));
assert(/class="sm accent held-main" onclick="deviationRepairHold\('cd34'\)"/.test(hh));
assert(hh.indexOf('Указать') < hh.indexOf('или:'));
assert(hh.indexOf('или:') < hh.indexOf('повторить шаг'));
assert(hh.indexOf('открыть устройство') < hh.indexOf('завершить со сбоем'));
assert(!hh.includes('продолжить как есть'));
// fail-кнопка только у fail: hold со скриншотом её не получает
assert.strictEqual(h.deviationRepairButton({...hold, shot: 's.png'}), '');
assert(!h.deviationCard({...hold, shot: 's.png'}).includes('Починить шаг'));
assert.strictEqual((hh.match(/sm accent/g) || []).length, 1);
assert.strictEqual((h.holdActions({...hold, scenario_key: ''}).match(/sm accent/g) || []).length, 1);
// сервер сказал «кликом не чинится» — кнопки нет, хоть данные и есть
ctx.S.jobs[0].repairable = false;
assert(!h.holdActions(hold).includes('Указать на снимке'));
ctx.S.jobs[0].repairable = true;
const plain = h.holdActions({...hold, scenario_key: ''});
assert(!plain.includes('Указать на снимке'));
// чинить кликом нечего — главным становится «открыть устройство»
assert(/held-main" onclick="deviationToDevice\('cd34'\)"/.test(plain));
ctx.S.jobs = []; toasts.length = 0; got = null;
h.deviationRepairHold('cd34');
assert.strictEqual(got, null);
assert.strictEqual(toasts[0][0], 'этого запуска уже нет в журнале');

// --- возврат фокуса
const fresh = {dataset: {id: 'x1'}, isConnected: true, className: 'dvn-shot'};
const freshBtn = {dataset: {id: 'x1'}, isConnected: true, className: 'sm accent'};
ctx.document.querySelectorAll = () => [{dataset: {id: 'zz'}, className: 'dvn-shot'}, freshBtn, fresh];
h.setModalReturn({dataset: {id: 'x1'}, isConnected: false, className: 'dvn-shot'});
h.repointModalReturn();
assert.strictEqual(h.getModalReturn(), fresh);
// кнопка починки находит именно кнопку, а не миниатюру с тем же id
h.setModalReturn({dataset: {id: 'x1'}, isConnected: false, className: 'sm accent'});
h.repointModalReturn();
assert.strictEqual(h.getModalReturn(), freshBtn);
assert(h.deviationRepairButton(fail).includes('data-id="ab12"'));
const live = {dataset: {id: 'x1'}, isConnected: true, className: 'dvn-shot'};
h.setModalReturn(live); h.repointModalReturn();
assert.strictEqual(h.getModalReturn(), live);
const noId = {dataset: {}, isConnected: false, className: ''};
h.setModalReturn(noId); h.repointModalReturn();
assert.strictEqual(h.getModalReturn(), noId);
h.setModalReturn(null); h.repointModalReturn();

// --- полоса HELD в журнале и на устройстве (jobs.js: decisionBar)
const job = {id: 'j9', serial: 's1', status: 'held', held_reason: 'нет цели',
             scenario_key: 'k', step_index: 2, artifacts: ['hold_1.jpg'], repairable: true};
const bar = ctx.decisionBar(job);
assert(/held-main" onclick="jobRepairHold\('j9'\)"/.test(bar));
// миниатюра ведёт туда же, куда главная кнопка, а не в новую вкладку
assert(/<button type="button" class="held-shot" onclick="jobRepairHold\('j9'\)"/.test(bar));
assert(bar.includes("openDevice('s1')"));
assert.strictEqual((bar.match(/accent/g) || []).length, 1);
// на самом устройстве «открыть устройство» лишнее
const onDev = ctx.decisionBar(job, {onDevice: true});
assert(!onDev.includes('openDevice'));
// шаг без номера: чинить кликом нечем — на устройстве главным становится повтор
const noStep = ctx.decisionBar({...job, step_index: -1}, {onDevice: true});
assert(/held-main" onclick="decideJob\('j9','retry'\)"/.test(noStep));
assert(!/ghost"[^>]*onclick="decideJob\('j9','retry'\)"/.test(noStep));
assert(/<a class="held-shot"/.test(noStep));
// шаг вслепую: вопрос «экран тот?», главное — продолжить
const blind = ctx.decisionBar({...job, held_kind: 'blind'});
assert(/held-main" onclick="decideJob\('j9','go'\)"/.test(blind));
assert(!blind.includes('jobRepairHold'));
assert(ctx.decisionBar({...job, status: 'running'}) === '');
assert(!ctx.decisionBar({...job, repairable: false}).includes('jobRepairHold'));
"""


def test_deviation_js_helpers():
    r = subprocess.run([require_node(), "-e", SCRIPT, str(JS), str(JOBS_JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
