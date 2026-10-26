"""Чистые помощники групп фраз (bulk.js, блок «группы фраз»)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* группы фраз: начало */'), b = src.indexOf('/* группы фраз: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';Object.assign(this,{phrAddItem,phrRemoveItem,phrInsertItem,phrAddGroup,'
  + 'phrRenameGroup,phrDeleteGroup,phrSetActive,phrNeighbor,phrFreeName,phrMigrate,phrGroup})', ctx);
const J = x => JSON.parse(JSON.stringify(x));
const base = () => ({groups: [{id: 'a', name: 'Общие', items: ['раз']}, {id: 'b', name: 'Кросс', items: []}], active: 'a'});

// добавление: чистит пробелы, не берёт пустое и повторы, соблюдает лимит
let r = J(ctx.phrAddItem(base(), '  два  '));
assert.deepStrictEqual(r.state.groups[0].items, ['раз', 'два']);
assert.strictEqual(r.ok, true);
assert.strictEqual(J(ctx.phrAddItem(base(), '   ')).reason, 'empty');
assert.strictEqual(J(ctx.phrAddItem(base(), 'раз')).reason, 'dup');
const full = base(); full.groups[0].items = Array.from({length: 100}, (_, i) => 'f' + i);
assert.strictEqual(J(ctx.phrAddItem(full, 'ещё')).reason, 'limit');
assert.strictEqual(J(ctx.phrAddItem(base(), 'x'.repeat(600))).state.groups[0].items[1].length, 500);
const orig = base(); ctx.phrAddItem(orig, 'новая');
assert.deepStrictEqual(J(orig), base());                       // исходное состояние не меняется

// добавляет в активную группу
const onB = base(); onB.active = 'b';
assert.deepStrictEqual(J(ctx.phrAddItem(onB, 'q')).state.groups[1].items, ['q']);

// удаление и возврат на место
assert.deepStrictEqual(J(ctx.phrRemoveItem(base(), 0)).groups[0].items, []);
assert.deepStrictEqual(J(ctx.phrRemoveItem(base(), 5)).groups[0].items, ['раз']);
const two = J(ctx.phrAddItem(base(), 'два').state);
assert.deepStrictEqual(J(ctx.phrInsertItem(ctx.phrRemoveItem(two, 0), 0, 'раз')).groups[0].items, ['раз', 'два']);

// новая группа становится активной; лимит 30
let g = J(ctx.phrAddGroup(base(), 'n1', '  Новая  '));
assert.strictEqual(g.ok, true);
assert.strictEqual(g.state.active, 'n1');
assert.strictEqual(g.state.groups[2].name, 'Новая');
const many = {groups: Array.from({length: 30}, (_, i) => ({id: 'g' + i, name: 'n', items: []})), active: 'g0'};
assert.strictEqual(J(ctx.phrAddGroup(many, 'z', 'Ещё')).ok, false);

// переименование: пустое имя игнорируется, длинное обрезается
assert.strictEqual(J(ctx.phrRenameGroup(base(), 'b', ' Дружба ')).groups[1].name, 'Дружба');
assert.strictEqual(J(ctx.phrRenameGroup(base(), 'b', '  ')).groups[1].name, 'Кросс');
assert.strictEqual(J(ctx.phrRenameGroup(base(), 'b', 'я'.repeat(60))).groups[1].name.length, 40);

// удаление группы: активной становится соседняя, последнюю не удалить
let d = J(ctx.phrDeleteGroup(base(), 'a'));
assert.deepStrictEqual(d.groups.map(x => x.id), ['b']);
assert.strictEqual(d.active, 'b');
assert.strictEqual(J(ctx.phrDeleteGroup(d, 'b')).groups.length, 1);
assert.strictEqual(J(ctx.phrDeleteGroup(base(), 'b')).active, 'a');

// переключение
assert.strictEqual(J(ctx.phrSetActive(base(), 'b')).active, 'b');
assert.strictEqual(J(ctx.phrSetActive(base(), 'нет')).active, 'a');
assert.strictEqual(ctx.phrNeighbor(base(), 1), 'b');
assert.strictEqual(ctx.phrNeighbor(base(), -1), 'b');         // по кругу
assert.strictEqual(ctx.phrFreeName(base(), 'Группа {n}'), 'Группа 3');

// переезд из браузера: только при пустой ферме и непустом списке
const empty = {groups: [{id: 'a', name: 'Общие', items: []}], active: 'a'};
assert.deepStrictEqual(J(ctx.phrMigrate(empty, ['x', ' y ', 'x', '', 5])).groups[0].items, ['x', 'y']);
assert.strictEqual(ctx.phrMigrate(base(), ['x']), null);       // на ферме уже есть фразы
assert.strictEqual(ctx.phrMigrate(empty, []), null);
assert.strictEqual(ctx.phrMigrate(empty, null), null);
assert.strictEqual(ctx.phrMigrate(empty, 'не список'), null);
assert.strictEqual(ctx.phrMigrate(null, ['x']), null);
assert.strictEqual(J(ctx.phrMigrate(empty, Array.from({length: 150}, (_, i) => 'p' + i))).groups[0].items.length, 100);
"""


def test_phrase_groups_helpers():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
