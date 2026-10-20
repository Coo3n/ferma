"""«Как нажимать» (findhow.js): клик → точка и обратно без потерь."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "findhow.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const steps = [{id: 1, kind: 'click', args: {}, selector: {call: 'click', args: 'text="Войти"'},
                or: ['description="Login"'], texts: ['Войти'], crop: 'AAA', point: [0.4, 0.8], note: 'Войти'}];
let saved = 0;
const ctx = {REC: {steps}, recFind: id => steps.find(s => s.id === id), recRender: () => {},
             recSave: () => { saved++; }, recPoint: b => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2],
             toast: () => {}, S: {}, document: {}, window: {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.howMode=howMode;this.howPick=(i,m)=>{}', ctx);
vm.runInContext('howPick = (id, mode) => { globalThis.__picked = mode; }', ctx);

// Клик → точка: координаты из записанной точки, элемент спрятан в _click.
ctx.howMode(1, 'point');
const s = steps[0];
assert.strictEqual(s.kind, 'tap');
assert.strictEqual(JSON.stringify(s.args), '{"x":0.4,"y":0.8}');
assert.strictEqual(s.selector, undefined);
assert.strictEqual(s.crop, undefined);
assert.ok(s._click && s._click.selector.args === 'text="Войти"');

// Точка → клик: всё вернулось, как было.
ctx.howMode(1, 'button');
assert.strictEqual(s.kind, 'click');
assert.strictEqual(s.selector.args, 'text="Войти"');
assert.strictEqual(JSON.stringify(s.or), JSON.stringify(['description="Login"']));
assert.strictEqual(s.crop, 'AAA');
assert.strictEqual(s._click, undefined);
assert.strictEqual(saved, 2);

// Тап без запаса (записан точкой) — «По кнопке» просит указать кнопку на экране.
steps.push({id: 2, kind: 'tap', args: {x: 0.1, y: 0.2}});
ctx.howMode(2, 'button');
assert.strictEqual(steps[1].kind, 'tap');
assert.strictEqual(ctx.__picked, 'button');
"""


def test_findhow_mode_roundtrip():
    r = subprocess.run([require_node(), "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
