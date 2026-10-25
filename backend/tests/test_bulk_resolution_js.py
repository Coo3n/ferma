"""Панель «Разрешение»: сводка по размерам и пропорции (bulk.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* разрешение: начало */'), b = src.indexOf('/* разрешение: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.sum=bulkResSummary;this.fit=bulkResFit', ctx);
const got = ctx.sum({
  A: {ok: true, size: [1080, 2400]}, B: {ok: true, size: [720, 1600]},
  C: {ok: true, size: [1080, 2400]}, D: {ok: false, error: 'offline'}, E: {ok: true, size: null},
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(got)),
  [{size: '1080×2400', count: 2, w: 1080, h: 2400}, {size: '720×1600', count: 1, w: 720, h: 1600}]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.sum(null))), []);
assert.strictEqual(ctx.fit(1080, 2400, 720), 1600);
assert.strictEqual(ctx.fit(1080, 2340, 720), 1560);
"""


def test_resolution_helpers():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
