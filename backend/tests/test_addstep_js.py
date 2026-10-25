"""«Добавить шаг» (addstep.js): какие пункты показать по месту вставки."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "addstep.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.plan=addStepPlan;this.search=addStepSearch', ctx);
const plan = c => JSON.parse(JSON.stringify(ctx.plan(Object.assign({depthMax: 3}, c))));
const keys = p => p.groups.map(g => g.key);
const items = (p, g) => p.groups.find(x => x.key === g).items;
const item = (p, k) => p.groups.flatMap(g => g.items).find(i => i.key === k);

// Обычное место: все разделы, по порядку из спеки; «выйти из повтора» нет.
let p = plan({sel: 0, depth: 0, inLoop: false, phone: true});
assert.strictEqual(p.wrap, false);
assert.deepStrictEqual(keys(p), ['action', 'mine', 'repeat', 'cond', 'other']);
const sub = (p, s) => items(p, 'cond').filter(i => i.sub === s).map(i => i.key);
assert.deepStrictEqual(sub(p, 'phone'),
    ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery', 'phone_offline', 'phone_space', 'phone_account']);
assert.deepStrictEqual(items(p, 'repeat').map(i => i.key), ['loop', 'until']);
assert.deepStrictEqual(sub(p, 'seen'), ['if_seen', 'if_not', 'anchor']);
assert.deepStrictEqual(sub(p, 'chance'), ['chance']);
assert.deepStrictEqual(items(p, 'other').map(i => i.key), ['budget', 'finish']);
assert.deepStrictEqual(items(p, 'mine').map(i => i.key), ['mine']);
assert.deepStrictEqual(items(p, 'action').map(i => i.key), ['presets', 'wait', 'wait_gone']);
assert.ok(p.groups.flatMap(g => g.items).every(i => i.off === null));

// Внутри повтора — появляется «выйти из повтора».
p = plan({sel: 0, depth: 1, inLoop: true, phone: true});
assert.deepStrictEqual(items(p, 'repeat').map(i => i.key), ['loop', 'until', 'break']);

// Без телефона «убедиться, что экран тот» выключен с причиной.
p = plan({sel: 0, depth: 0, inLoop: false, phone: false});
assert.strictEqual(item(p, 'anchor').off, 'phone');
assert.strictEqual(item(p, 'loop').off, null);

// На предельной глубине новый блок не встанет — блоки выключены, остальное нет.
p = plan({sel: 0, depth: 3, inLoop: true, phone: true});
for (const k of ['loop', 'until', 'if_seen', 'if_not', 'chance', 'phone_app', 'phone_battery']) assert.strictEqual(item(p, k).off, 'deep');
for (const k of ['break', 'anchor', 'mine', 'finish']) assert.strictEqual(item(p, k).off, null);

// Выбраны шаги: только блоки (их берут внутрь), без действий, проверки
// экрана, «выйти из повтора» и «другого». Глубину проверит recBlockWrap.
p = plan({sel: 2, depth: 3, inLoop: true, phone: true});
assert.strictEqual(p.wrap, true);
assert.deepStrictEqual(keys(p), ['repeat', 'cond']);
assert.deepStrictEqual(p.groups.flatMap(g => g.items).map(i => i.key),
    ['loop', 'until', 'if_seen', 'if_not', 'phone_app', 'phone_no_app', 'phone_older', 'phone_battery',
     'phone_offline', 'phone_space', 'phone_account', 'chance']);
assert.ok(p.groups.flatMap(g => g.items).every(i => i.off === null));

// Поиск: все слова (AND), подстрока, регистр и ё/е не важны, порядок исходный.
const cards = [
    {key: 'a', title: 'Двойной тап', desc: 'два быстрых нажатия', words: 'дабл'},
    {key: 'b', title: 'Пауза', desc: 'подождать', words: 'случайная пауза ёлка'},
    {key: 'c', title: 'Включить прокси', desc: 'для аккаунта', words: ''},
    {key: 'd', title: 'Пауза перед прокси', desc: '', words: ''},
];
const find2 = () => JSON.parse(JSON.stringify(ctx.search('x', null)));
const find = q => JSON.parse(JSON.stringify(ctx.search(q, cards).map(c => c.key)));
assert.deepStrictEqual(find('пауза'), ['b', 'd']);
assert.deepStrictEqual(find('ПАУЗ'), ['b', 'd']);
assert.deepStrictEqual(find('пауза прокси'), ['d']);
assert.deepStrictEqual(find('  прокси   пауза '), ['d']);
assert.deepStrictEqual(find('елка'), ['b']);
assert.deepStrictEqual(find('ЁЛКА'), ['b']);
assert.deepStrictEqual(find('дабл'), ['a']);
assert.deepStrictEqual(find('аккаунт'), ['c']);
assert.deepStrictEqual(find(''), []);
assert.deepStrictEqual(find('   '), []);
assert.deepStrictEqual(find('зебра'), []);
assert.deepStrictEqual(find('пауза зебра'), []);
assert.deepStrictEqual(find2(), []);

// Короткое слово — по началу слова: «ip» не должно находить «swipe».
const net = [
    {key: 's', title: 'Свайп вверх', desc: '', words: 'swipe свайп'},
    {key: 'n', title: 'Сменить IP', desc: '', words: 'ip айпи'},
    {key: 'c', title: 'Скрыть клавиатуру', desc: '', words: 'clip'},
];
const findNet = q => JSON.parse(JSON.stringify(ctx.search(q, net).map(c => c.key)));
assert.deepStrictEqual(findNet('ip'), ['n']);
assert.deepStrictEqual(findNet('swi'), ['s']);
assert.deepStrictEqual(findNet('свайп'), ['s']);
// От четырёх букв — подстрока: ловит формы слова.
assert.deepStrictEqual(findNet('вайп'), ['s']);
"""


def test_addstep_plan():
    node = require_node()
    res = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
