"""Сводка уведомлений по приложениям (tool-notify.js: notifSummary)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "tool-notify.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {toolsRegister() {}, esc: s => String(s), t: k => k};
vm.createContext(ctx);
vm.runInContext(src + ';this.sum=notifSummary', ctx);
const got = ctx.sum({
  A: {name: 'Т1', count: 2, items: [{pkg: 'com.whatsapp'}, {pkg: 'com.whatsapp'}]},
  B: {name: 'Т2', count: 1, items: [{pkg: 'com.whatsapp'}]},
  C: {name: 'Т3', count: 1, items: [{pkg: 'org.telegram.messenger'}]},
  D: {name: 'Т4', count: 0, items: []},
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(got)), [
  {pkg: 'com.whatsapp', phones: 2, total: 3},
  {pkg: 'org.telegram.messenger', phones: 1, total: 1},
]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(ctx.sum({}))), []);
"""


def test_notif_summary():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
