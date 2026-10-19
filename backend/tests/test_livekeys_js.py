"""Живая клавиатура (livekeys.js): склейка текста, повтор клавиш, разбор событий."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "livekeys.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8')
    + ';this.api={liveKeyOp,liveKeyMerge,liveKeyActions,liveInputOp}', ctx);
const j = v => JSON.parse(JSON.stringify(v));
const {liveKeyOp, liveKeyMerge, liveKeyActions, liveInputOp} = ctx.api;

// буквы склеиваются в одно действие, порядок сохраняется
let q = [];
for (const ch of 'при') liveKeyMerge(q, liveKeyOp({key: ch}));
liveKeyMerge(q, liveKeyOp({key: 'Enter'}));
liveKeyMerge(q, liveKeyOp({key: 'в'}));
assert.deepStrictEqual(j(liveKeyActions(q)), [
    {type: 'text', value: 'при'}, {type: 'key', name: 'enter'}, {type: 'text', value: 'в'}]);

// удержанный Backspace — один запрос со счётчиком
q = [];
for (let i = 0; i < 5; i++) liveKeyMerge(q, liveKeyOp({key: 'Backspace'}));
assert.deepStrictEqual(j(liveKeyActions(q)), [{type: 'key', name: 'delete', count: 5}]);

// IME / неопознанное — отложить на input; Ctrl+буква — не наше
assert.strictEqual(liveKeyOp({key: 'Process'}), 'defer');
assert.strictEqual(liveKeyOp({key: 'a', isComposing: true}), 'defer');
assert.strictEqual(liveKeyOp({key: 'v', ctrlKey: true}), null);
assert.strictEqual(liveKeyOp({key: 'Shift'}), null);

// виртуальная клавиатура
assert.deepStrictEqual(j(liveInputOp('insertText', 'ы')), {k: 'text', v: 'ы'});
assert.deepStrictEqual(j(liveInputOp('deleteContentBackward', null)), {k: 'key', name: 'delete', n: 1});
assert.strictEqual(liveInputOp('historyUndo', null), null);
"""


def test_livekeys():
    node = require_node()
    r = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
