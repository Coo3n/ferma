"""F1–F9 вводят быстрые фразы (bulk.js: phraseForHotkey)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* горячие клавиши фраз: начало */'), b = src.indexOf('/* горячие клавиши фраз: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.f=phraseForHotkey', ctx);
const list = ['раз', 'два', 'три'];
const key = (k, extra) => Object.assign({key: k}, extra || {});
assert.strictEqual(ctx.f(key('F1'), list), 'раз');
assert.strictEqual(ctx.f(key('F3'), list), 'три');
assert.strictEqual(ctx.f(key('F4'), list), null);          // фразы с таким номером нет
assert.strictEqual(ctx.f(key('F10'), list), null);         // только F1–F9
assert.strictEqual(ctx.f(key('F0'), list), null);
assert.strictEqual(ctx.f(key('a'), list), null);
assert.strictEqual(ctx.f(key('F1', {ctrlKey: true}), list), null);
assert.strictEqual(ctx.f(key('F1', {shiftKey: true}), list), null);
assert.strictEqual(ctx.f(key('F1'), []), null);
"""


def test_phrase_hotkey():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
