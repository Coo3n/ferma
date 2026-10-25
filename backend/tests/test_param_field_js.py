"""Поле параметра сценария: textarea для списков слов и фраз (scenarios.js: paramField)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "scenarios.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function paramField'), b = src.indexOf('/* Настройки сценария');
const ctx = {esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.f=paramField', ctx);
const html = ctx.f('words', {type: 'textarea', placeholder: 'по строке'}, 'a\nb<c');
assert.ok(html.startsWith('<textarea id="p_words"'), html);
assert.ok(html.includes('rows="4"'));
assert.ok(html.includes('placeholder="по строке"'));
assert.ok(html.includes('a\nb&lt;c</textarea>'));
// остальные типы не сломаны
assert.ok(ctx.f('n', {type: 'number'}, 5).includes('type="number"'));
assert.ok(ctx.f('t', {}, 'x').includes('type="text"'));
assert.ok(ctx.f('s', {options: ['a', 'b']}, 'b').includes('<select'));
"""


def test_textarea_param_field():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
