"""«Добавить шаг» (addstep.js): какие пункты показать по месту вставки."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "addstep.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.plan=addStepPlan', ctx);
const plan = c => JSON.parse(JSON.stringify(ctx.plan(Object.assign({depthMax: 3}, c))));
const keys = p => p.groups.map(g => g.key);
const items = (p, g) => p.groups.find(x => x.key === g).items;
const item = (p, k) => p.groups.flatMap(g => g.items).find(i => i.key === k);

// Обычное место: все разделы, по порядку из спеки; «выйти из повтора» нет.
let p = plan({sel: 0, depth: 0, inLoop: false, phone: true});
assert.strictEqual(p.wrap, false);
assert.deepStrictEqual(keys(p), ['repeat', 'seen', 'phone', 'chance', 'action', 'other']);
assert.deepStrictEqual(items(p, 'phone').map(i => i.key),
    ['phone_app', 'phone_no_app', 'phone_older', 'phone_battery', 'phone_offline', 'phone_space', 'phone_account']);
assert.deepStrictEqual(items(p, 'repeat').map(i => i.key), ['loop', 'until']);
assert.deepStrictEqual(items(p, 'seen').map(i => i.key), ['if_seen', 'if_not', 'anchor']);
assert.deepStrictEqual(items(p, 'other').map(i => i.key), ['call', 'finish']);
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
for (const k of ['break', 'anchor', 'call', 'finish']) assert.strictEqual(item(p, k).off, null);

// Выбраны шаги: только блоки (их берут внутрь), без действий, проверки
// экрана, «выйти из повтора» и «другого». Глубину проверит recBlockWrap.
p = plan({sel: 2, depth: 3, inLoop: true, phone: true});
assert.strictEqual(p.wrap, true);
assert.deepStrictEqual(keys(p), ['repeat', 'seen', 'phone', 'chance']);
assert.deepStrictEqual(p.groups.flatMap(g => g.items).map(i => i.key),
    ['loop', 'until', 'if_seen', 'if_not', 'phone_app', 'phone_no_app', 'phone_older', 'phone_battery',
     'phone_offline', 'phone_space', 'phone_account', 'chance']);
assert.ok(p.groups.flatMap(g => g.items).every(i => i.off === null));
"""


def test_addstep_plan():
    node = require_node()
    res = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
