"""Таблица здоровья: строки, подсветка, порядок (tool-health.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "tool-health.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {toolsRegister() {}, esc: s => String(s), t: k => k};
vm.createContext(ctx);
vm.runInContext(src + ';this.rows=healthRows', ctx);
const rows = ctx.rows([
  {online: true, name: 'Б', battery: 80, temperature: 30, rom_used: 50, ram_free: 40, cpu: 10},
  {online: true, name: 'А', battery: 10, temperature: 45, rom_used: 95, ram_free: 5, cpu: 90},
  {online: false, name: 'Офлайн', battery: 1},
  {online: true, name: 'В', battery: null, temperature: null, rom_used: null, ram_free: null, cpu: null},
]);
assert.deepStrictEqual(JSON.parse(JSON.stringify(rows.map(r => r.name))), ['А', 'Б', 'В']);      // больше проблем — выше, дальше по имени; офлайн не берём
assert.deepStrictEqual(JSON.parse(JSON.stringify([...rows[0].bad].sort())), ['battery', 'ram', 'rom', 'temp']);
assert.deepStrictEqual(JSON.parse(JSON.stringify(rows[1].bad)), []);                              // нет данных — не тревога
"""


def test_health_rows():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
