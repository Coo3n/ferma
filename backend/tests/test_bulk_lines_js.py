"""Панель «Каждому своё»: разбор строк файла и предпросмотр (bulk.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* строки: начало */'), b = src.indexOf('/* строки: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.rows=bulkLinesRows;this.plan=bulkLinesPlan', ctx);
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.rows(' a \n\nb\r\n c '))), ['a', 'b', 'c']);
assert.strictEqual(ctx.rows('x\n'.repeat(9000)).length, 5000);
const plan = ctx.plan(['Т1', 'Т2', 'Т3'], ['one', 'two'], 'order');
assert.deepStrictEqual(JSON.parse(JSON.stringify(plan)), [
  {name: 'Т1', text: 'one'}, {name: 'Т2', text: 'two'}, {name: 'Т3', text: null}]);
const cyc = ctx.plan(['Т1', 'Т2', 'Т3'], ['one', 'two'], 'cycle');
assert.deepStrictEqual(JSON.parse(JSON.stringify(cyc.map(x => x.text))), ['one', 'two', 'one']);
"""


def test_lines_helpers():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
