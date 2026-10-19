"""Черновик конструктора (draft.js): когда о нём спрашивать."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "draft.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {t: (k, v) => k + (v ? JSON.stringify(v) : '')};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.plan=draftPlan;this.ago=draftAgo', ctx);
const NOW = 1e12, H = 3600e3, D = 24 * H;
const d = (n, age) => ({steps: Array(n).fill({}), savedAt: age == null ? undefined : NOW - age});

assert.strictEqual(ctx.plan(null, NOW, false), 'drop');
assert.strictEqual(ctx.plan(d(0, 0), NOW, false), 'drop');
assert.strictEqual(ctx.plan(d(1, 0), NOW, false), 'drop');          // один шаг — не работа
assert.strictEqual(ctx.plan(d(5, 2 * H), NOW, false), 'ask');
assert.strictEqual(ctx.plan(d(5, 2 * H), NOW, true), 'skip');       // «Не сейчас»
assert.strictEqual(ctx.plan(d(5, 8 * D), NOW, false), 'drop');      // старше недели
assert.strictEqual(ctx.plan(d(5, 8 * D), NOW, true), 'drop');
assert.strictEqual(ctx.plan(d(5, 6 * D), NOW, false), 'ask');
assert.strictEqual(ctx.plan(d(5, undefined), NOW, false), 'ask');   // без метки времени — не старый

assert.ok(ctx.ago(NOW - 10e3, NOW).startsWith('draft.tolko_chto'));
assert.ok(ctx.ago(NOW - 5 * 60e3, NOW).startsWith('draft.min_nazad'));
assert.ok(ctx.ago(NOW - 2 * H, NOW).startsWith('draft.ch_nazad'));
assert.ok(ctx.ago(NOW - 3 * D, NOW).startsWith('draft.dn_nazad'));
assert.strictEqual(ctx.ago(0, NOW), '');
"""


def test_draft_plan():
    node = require_node()
    r = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
