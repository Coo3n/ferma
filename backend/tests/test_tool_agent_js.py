"""ИИ-агент (tool-agent.js): конечный автомат, слова про действия, метки на кадре."""
import subprocess
from pathlib import Path

from _node import require_node

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "frontend" / "js" / "tool-agent.js"
STRINGS = ROOT / "frontend" / "strings" / "ru.json"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const S = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ctx = {
  toolsRegister() {}, esc: s => String(s).replace(/[&<>"]/g, c => '&#' + c.charCodeAt(0) + ';'),
  t: (k, v) => (S[k] || k).replace(/\{(\w+)\}/g, (m, n) => v && v[n] != null ? v[n] : m),
  document: {addEventListener() {}}, window: {}, store: {get: (k, d) => d, set() {}},
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `;this.api = {
  next: agentNext, init: agentInit, text: agentActionText, words: agentStepWords, ret: agentReticle,
  arrow: agentArrow, reply: agentReplyEvent, prog: agentProgress, banner: agentBanner,
  canSave: agentCanSave, hist: agentHistoryForApi, dir: agentSwipeDir, clamp: agentClampLimit,
  running: agentRunning, tl: agentTimelineHtml}`, ctx);
const A = ctx.api;
const J = x => JSON.parse(JSON.stringify(x));
const tap = {kind: 'tap', x: 0.5, y: 0.4};
const run = (s, ...evs) => evs.reduce((st, e) => J(A.next(st, e)), s);

// 1. Обычный ход: idle → thinking → proposed → doing → thinking → done
let s = A.init();
assert.strictEqual(s.phase, 'idle');
s = run(s, {type: 'start'});
assert.strictEqual(s.phase, 'thinking');
s = run(s, {type: 'proposal', action: tap, why: 'открыть'});
assert.strictEqual(s.phase, 'proposed');
assert.deepStrictEqual(s.proposal, {action: tap, why: 'открыть'});
s = run(s, {type: 'execute'});
assert.strictEqual(s.phase, 'doing');
s = run(s, {type: 'executed'});
assert.strictEqual(s.phase, 'thinking');
assert.deepStrictEqual(s.history, [{action: tap, why: 'открыть', result: 'ok'}]);
assert.strictEqual(s.proposal, null);
s = run(s, {type: 'done', why: 'всё'});
assert.strictEqual(s.phase, 'done');
assert.strictEqual(s.reason, 'всё');
assert.ok(A.canSave(s));

// 2. Пропуск попадает в историю, но не считается выполненным
s = run(A.init(), {type: 'start'}, {type: 'proposal', action: tap}, {type: 'skip'});
assert.strictEqual(s.phase, 'thinking');
assert.strictEqual(s.history[0].result, 'skipped');
s = run(s, {type: 'stop'});
assert.ok(!A.canSave(s), 'без выполненных шагов сохранять нечего');

// 3. «Нужен человек»
s = run(A.init(), {type: 'start'}, {type: 'ask', why: 'нужен код из СМС'});
assert.strictEqual(s.phase, 'needs_human');
assert.strictEqual(s.reason, 'нужен код из СМС');

// 4. Режим «сам» не ждёт ответа и не выходит за предел
s = run(A.init(), {type: 'auto', on: true, limit: 3}, {type: 'start'});
assert.strictEqual(s.auto, true);
for (let i = 0; i < 3; i++) {
  assert.strictEqual(s.phase, 'thinking', 'шаг ' + i);
  s = run(s, {type: 'proposal', action: tap, why: 'шаг'});
  assert.strictEqual(s.phase, 'doing', 'сам: сразу выполняет');
  s = run(s, {type: 'executed'});
}
assert.strictEqual(s.phase, 'stopped');
assert.strictEqual(s.reason, 'limit');
assert.strictEqual(s.history.length, 3);
s = run(s, {type: 'proposal', action: tap});
assert.strictEqual(s.phase, 'stopped', 'после предела предложения не берутся');
assert.strictEqual(s.history.length, 3);

// предел не выше общего, не ниже единицы; мусор → значение по умолчанию
assert.strictEqual(A.clamp(99), 30);
assert.strictEqual(A.clamp(0), 15);
assert.strictEqual(A.clamp('abc'), 15);
assert.strictEqual(A.clamp(7.9), 7);
s = run(A.init(), {type: 'auto', on: true, limit: 500});
assert.strictEqual(s.limit, 30);

// пропуск тоже считается шагом
s = run(A.init(), {type: 'auto', on: false, limit: 2}, {type: 'start'});
assert.strictEqual(s.phase, 'thinking');

// 5. Стоп из любого рабочего состояния
for (const evs of [
  [{type: 'start'}],
  [{type: 'start'}, {type: 'proposal', action: tap}],
  [{type: 'start'}, {type: 'proposal', action: tap}, {type: 'execute'}],
  [{type: 'start'}, {type: 'error', message: 'x'}],
]) {
  const st = run(A.init(), ...evs, {type: 'stop'});
  assert.strictEqual(st.phase, 'stopped', JSON.stringify(evs));
  assert.strictEqual(st.reason, 'user');
}
// пока шло действие — оно всё равно случилось и попадает в историю
s = run(A.init(), {type: 'start'}, {type: 'proposal', action: tap, why: 'w'}, {type: 'execute'}, {type: 'stop'});
assert.strictEqual(s.phase, 'stopped');
s = run(s, {type: 'executed'});
assert.strictEqual(s.phase, 'stopped');
assert.strictEqual(s.history.length, 1);
assert.strictEqual(s.history[0].result, 'ok');
// стоп у готового сеанса его не затирает
s = run(A.init(), {type: 'start'}, {type: 'done', why: 'ok'}, {type: 'stop'});
assert.strictEqual(s.phase, 'done');
// limit из любого рабочего
s = run(A.init(), {type: 'start'}, {type: 'limit'});
assert.strictEqual(s.phase, 'stopped');
assert.strictEqual(s.reason, 'limit');

// 6. Ошибка не теряет историю; «Повторить шаг»
s = run(A.init(), {type: 'start'}, {type: 'proposal', action: tap, why: 'a'}, {type: 'execute'}, {type: 'executed'},
        {type: 'proposal', action: {kind: 'key', name: 'back'}, why: 'b'}, {type: 'execute'},
        {type: 'error', message: 'телефон не отвечает'});
assert.strictEqual(s.phase, 'error');
assert.strictEqual(s.error, 'телефон не отвечает');
assert.strictEqual(s.history.length, 1);
assert.deepStrictEqual(s.proposal.action, {kind: 'key', name: 'back'});
assert.ok(A.canSave(s), 'есть выполненный шаг — можно сохранить');
let r = run(s, {type: 'retry'});
assert.strictEqual(r.phase, 'doing');
assert.strictEqual(r.history.length, 1);
// ошибка при запросе шага — повтор снова смотрит на экран
s = run(A.init(), {type: 'start'}, {type: 'error', message: 'нет связи'}, {type: 'retry'});
assert.strictEqual(s.phase, 'thinking');
assert.strictEqual(s.error, '');

// 7. Лишние события не ломают
s = run(A.init(), {type: 'execute'}, {type: 'executed'}, {type: 'skip'}, {type: 'proposal', action: tap}, {type: 'bogus'});
assert.strictEqual(s.phase, 'idle');
s = run(A.init(), {type: 'start'}, {type: 'start'});
assert.strictEqual(s.phase, 'thinking');
// новый запуск после остановки стирает историю
s = run(A.init(), {type: 'start'}, {type: 'proposal', action: tap}, {type: 'execute'}, {type: 'executed'}, {type: 'stop'},
        {type: 'start'});
assert.strictEqual(s.phase, 'thinking');
assert.strictEqual(s.history.length, 0);
// reset оставляет настройки «сам»
s = run(A.init(), {type: 'auto', on: true, limit: 5}, {type: 'start'}, {type: 'stop'}, {type: 'reset'});
assert.strictEqual(s.phase, 'idle');
assert.strictEqual(s.auto, true);
assert.strictEqual(s.limit, 5);
// автомат чистый: входное состояние не меняется
const frozen = J(run(A.init(), {type: 'start'}, {type: 'proposal', action: tap}));
const copy = J(frozen);
A.next(frozen, {type: 'skip'});
assert.deepStrictEqual(J(frozen), copy);

// 8. Прогресс «шаг N из M»
s = run(A.init(), {type: 'auto', on: true, limit: 10}, {type: 'start'});
assert.deepStrictEqual(J(A.prog(s)), {n: 1, m: 10, pct: 10});
s = run(s, {type: 'proposal', action: tap}, {type: 'executed'});
assert.deepStrictEqual(J(A.prog(s)), {n: 2, m: 10, pct: 20});
s = run(s, {type: 'done'});
assert.deepStrictEqual(J(A.prog(s)), {n: 1, m: 10, pct: 10});
assert.strictEqual(A.prog(A.init()).n, 0);
assert.strictEqual(A.prog(run(A.init(), {type: 'start'})).m, 30);

// 9. Полоса состояния: у каждого состояния свой тон
const tones = ['thinking', 'proposed', 'doing', 'done', 'needs_human', 'stopped', 'error']
  .map(p => A.banner({phase: p}).tone);
assert.strictEqual(new Set(tones).size, 7, 'семь состояний — семь разных тонов');
assert.strictEqual(A.banner({phase: 'idle'}).key, '');
assert.strictEqual(A.banner({phase: 'done'}).key, 'agent.gotovo');
assert.ok(A.running({phase: 'thinking'}) && A.running({phase: 'doing'}) && !A.running({phase: 'proposed'}));

// 10. Ответ сервера → событие
assert.deepStrictEqual(J(A.reply({action: tap, why: 'w', step_no: 2, left: 5})),
    {type: 'proposal', action: tap, why: 'w', step_no: 2});
assert.deepStrictEqual(J(A.reply({done: true, why: 'x'})), {type: 'done', why: 'x'});
assert.deepStrictEqual(J(A.reply({ask: true, why: 'y'})), {type: 'ask', why: 'y'});
assert.strictEqual(A.reply({}).type, 'error');
assert.strictEqual(A.reply(null).type, 'error');
// история для сервера — только action/why/result
assert.deepStrictEqual(J(A.hist([{action: tap, why: 'w', result: 'ok', extra: 1}])),
    [{action: tap, why: 'w', result: 'ok'}]);

// 11. Действия простыми словами
const T = a => A.text(a);
assert.strictEqual(T(tap), 'Нажать в точку');
assert.strictEqual(T({kind: 'swipe', x1: .5, y1: .8, x2: .5, y2: .2}), 'Провести вверх');
assert.strictEqual(T({kind: 'swipe', x1: .5, y1: .2, x2: .5, y2: .8}), 'Провести вниз');
assert.strictEqual(T({kind: 'swipe', x1: .8, y1: .5, x2: .2, y2: .5}), 'Провести влево');
assert.strictEqual(T({kind: 'swipe', x1: .2, y1: .5, x2: .8, y2: .5}), 'Провести вправо');
assert.strictEqual(T({kind: 'swipe', x1: .5, y1: .5, x2: .5, y2: .5}), 'Провести по экрану');
assert.strictEqual(T({kind: 'type', value: 'привет'}), 'Ввести «привет»');
assert.ok(T({kind: 'type', value: 'я'.repeat(100)}).length < 80);
assert.strictEqual(T({kind: 'key', name: 'back'}), 'Нажать «Назад»');
assert.strictEqual(T({kind: 'key', name: 'home'}), 'Нажать «Домой»');
assert.strictEqual(T({kind: 'key', name: 'zzz'}), 'Нажать клавишу');
assert.strictEqual(T({kind: 'key', name: 'constructor'}), 'Нажать клавишу');
assert.strictEqual(T({kind: 'launch_app', package: 'org.telegram.messenger'}), 'Открыть приложение');
assert.ok(!T({kind: 'launch_app', package: 'org.telegram.messenger'}).includes('telegram'));
assert.strictEqual(T({kind: 'open_url', url: 'https://www.example.com/a?b=1'}), 'Открыть ссылку example.com');
assert.strictEqual(T({kind: 'open_url', url: 'мусор'}), 'Открыть ссылку');
assert.strictEqual(T({kind: 'wait', seconds: 3}), 'Подождать 3 с');
assert.strictEqual(T({kind: 'wait', seconds: 2.5}), 'Подождать 2.5 с');
assert.strictEqual(T({kind: 'zzz'}), 'Выполнить действие');
assert.strictEqual(T(null), 'Выполнить действие');
// шаги чернового рецепта — теми же словами
assert.strictEqual(A.words({kind: 'sleep', args: {seconds: 4}}), 'Подождать 4 с');
assert.strictEqual(A.words({kind: 'tap', args: {x: 10, y: 20}}), 'Нажать в точку');
assert.strictEqual(A.words({kind: 'type', args: {value: 'hi'}}), 'Ввести «hi»');
assert.strictEqual(A.words({kind: 'key', args: {name: 'back'}}), 'Нажать «Назад»');
// в тексте нет сырых имён и координат
for (const a of [tap, {kind: 'swipe', x1: .1, y1: .9, x2: .1, y2: .1}]) assert.ok(!/\d/.test(T(a)));

// 12. Метка на кадре
assert.deepStrictEqual(J(A.ret(0.5, 0.25)), {left: 50, top: 25});
assert.deepStrictEqual(J(A.ret(1.4, -3)), {left: 100, top: 0});
assert.deepStrictEqual(J(A.ret('x', NaN)), {left: 0, top: 0});
assert.deepStrictEqual(J(A.ret(0.3333, 0.6667)), {left: 33.3, top: 66.7});
let ar = J(A.arrow({x1: .5, y1: .8, x2: .5, y2: .2}, 1000, 2000));
assert.deepStrictEqual([ar.x1, ar.y1, ar.x2, ar.y2], [500, 1600, 500, 400]);
assert.strictEqual(ar.len, 1200);
const pts = ar.head.split(' ').map(p => p.split(',').map(Number));
assert.strictEqual(pts.length, 3);
assert.deepStrictEqual(pts[0], [500, 400], 'остриё — в конце свайпа');
assert.ok(pts[1][1] > 400 && pts[2][1] > 400, 'основание наконечника — позади острия');
assert.ok(pts[1][0] !== pts[2][0] && Math.abs(pts[1][0] + pts[2][0] - 1000) < 0.2, 'симметричен');
ar = J(A.arrow({x1: .5, y1: .5, x2: .5, y2: .5}, 100, 100));
assert.strictEqual(ar.head, '');
ar = J(A.arrow({x1: -1, y1: 2, x2: 9, y2: 0}, 100, 200));
assert.deepStrictEqual([ar.x1, ar.y1, ar.x2, ar.y2], [0, 200, 100, 0]);
assert.strictEqual(A.dir({x1: 0, y1: 0, x2: 0.5, y2: 0.1}), 'right');

// 13. Лента: карточки по порядку, экранирование
s = run(A.init(), {type: 'start'}, {type: 'proposal', action: tap, why: '<b>x</b>'}, {type: 'execute'}, {type: 'executed'},
        {type: 'proposal', action: {kind: 'type', value: 'a<i>'}, why: 'ввод'});
const html = A.tl(s);
assert.strictEqual((html.match(/<li /g) || []).length, 2);
assert.ok(html.indexOf('data-st="ok"') < html.indexOf('data-st="wait"'));
assert.ok(html.includes('Агент предлагает') && html.includes('Выполнено'));
assert.ok(!html.includes('<b>x</b>') && !html.includes('<i>'));
s = run(A.init(), {type: 'start'}, {type: 'proposal', action: tap}, {type: 'skip'});
assert.ok(A.tl(s).includes('Пропущено'));
"""


def test_agent_js():
    node = require_node()
    r = subprocess.run([node, "-e", SCRIPT, str(JS), str(STRINGS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
