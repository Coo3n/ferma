"""Окно «Инструменты»: реестр вкладок и плитки (tools.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "tools.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {
  esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'),
  t: k => k,
};
vm.createContext(ctx);
vm.runInContext(src + ';this.reg=toolsRegister;this.tiles=toolsTilesHtml;this.list=TOOLS;this.back=toolsBackButton', ctx);
ctx.reg({id: 'health', icon: 'sliders', title: 'Здоровье <b>', sub: 'ОЗУ и память', open() {}});
ctx.reg({id: 'backup', icon: 'download', title: 'Копия', sub: 'архив', open() {}});
assert.strictEqual(ctx.list.length, 2);
const html = ctx.tiles(ctx.list);
assert.ok(html.includes("toolsRun('health')") && html.includes("toolsRun('backup')"));
assert.ok(html.includes('Здоровье &lt;b&gt;'), 'заголовок экранируется');
assert.ok(html.includes('#i-sliders'));
assert.ok(ctx.back().includes('toolsOpen()'));
// повторная регистрация того же id заменяет вкладку, а не дублирует
ctx.reg({id: 'health', icon: 'x', title: 'Новое', sub: '', open() {}});
assert.strictEqual(ctx.list.length, 2);
assert.strictEqual(ctx.list.find(x => x.id === 'health').title, 'Новое');
"""


def test_tools_registry_and_tiles():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
