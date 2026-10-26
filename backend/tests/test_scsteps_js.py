"""Список «Что делает» панели сценария (scenarios.js, scStepsListHtml) — под node."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "scenarios.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {
  esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'),
  t: k => k, document: {}, window: {},
};
vm.createContext(ctx);
vm.runInContext(src + ';this.fn=scStepsListHtml', ctx);
assert.strictEqual(ctx.fn([]), '');
assert.strictEqual(ctx.fn(null), '');
const html = ctx.fn([{text: 'Открыть <b>', depth: 0}, {text: 'Нажать', depth: 2}, {text: 'x', depth: -3}, {text: 'y', depth: 'z'}]);
assert.ok(html.includes('Открыть &lt;b&gt;'), 'экранирование');
assert.ok(!html.includes('<b>'));
assert.ok(html.includes('--d:2'), 'глубина');
assert.strictEqual((html.match(/<li/g) || []).length, 4, 'по строке на шаг');
assert.ok(html.startsWith('<ol'), 'нумерованный список');
assert.ok(!html.includes('--d:-'), 'отрицательная глубина обнуляется');
"""


def test_sc_steps_list_html():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
