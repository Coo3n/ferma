"""uikeep.js: перерисовка опросом не сбрасывает фокус и раскрытые details."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "uikeep.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');

/* Крошечная подделка DOM: ровно то, что трогает uikeep.js. */
function el(tag, attrs, parent) {
    const node = {tagName: tag, attrs: Object.assign({}, attrs || {}), parent: parent || null,
        open: false, disabled: false, className: (attrs && attrs.class) || '',
        get id() { return this.attrs.id || ''; },
        getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
        closest(sel) {
            for (let n = this; n; n = n.parent) if (sel === '[data-id]' && n.attrs['data-id'] != null) return n;
            return null;
        },
        focus() { doc.activeElement = this; },
    };
    return node;
}
const doc = {body: {tagName: 'BODY'}, activeElement: null};

function box(build) {
    const b = {all: [], contains(n) { return this.all.includes(n); }};
    b.querySelectorAll = sel => sel === 'details'
        ? b.all.filter(n => n.tagName === 'DETAILS')
        : b.all.filter(n => n.id || ['onclick', 'onchange', 'oninput', 'data-f'].some(k => n.getAttribute(k) != null));
    b.build = () => { b.all = build(); };
    b.build();
    return b;
}

const ctx = {document: doc};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8')
    + ';this.h={uiFocusKey,uiOpenKeys,keepUi}', ctx);
const h = ctx.h;

// Ключ фокуса: id важнее всего; без id — обработчик и строка.
assert.strictEqual(h.uiFocusKey(el('BUTTON', {id: 'go'})), '#go');
const row = el('DIV', {'data-id': '7'});
assert.strictEqual(h.uiFocusKey(el('INPUT', {onchange: 'f(7)'}, row)), 'INPUT|7|f(7)');
assert.strictEqual(h.uiFocusKey(el('SPAN', {})), '');
assert.strictEqual(h.uiFocusKey(null), '');

// Одинаковые details различает номер по порядку.
const d1 = el('DETAILS', {class: 'more'}, row), d2 = el('DETAILS', {class: 'more'}, row);
d2.open = true;
assert.deepStrictEqual([...h.uiOpenKeys([d1, d2])], ['7|more#2']);

// Перерисовка: фокус и раскрытие переезжают на новые узлы того же смысла.
let gen = 0;
const b = box(() => {
    gen++;
    const r = el('DIV', {'data-id': '3'});
    return [el('BUTTON', {onclick: "pickJob('a')"}), el('BUTTON', {onclick: "pickJob('b')"}),
        el('DETAILS', {class: 'rs-more'}, r)];
});
b.all[1].focus();
b.all[2].open = true;
h.keepUi(b, () => { doc.activeElement = doc.body; b.build(); });
assert.strictEqual(gen, 2);
assert.strictEqual(doc.activeElement, b.all[1]);
assert.strictEqual(b.all[2].open, true);

// Закрытый details разметка может открыть сама — keepUi его не закрывает.
const c = box(() => [el('DETAILS', {class: 'x'})]);
h.keepUi(c, () => { c.build(); c.all[0].open = true; });
assert.strictEqual(c.all[0].open, true);

// Фокус вне узла не трогаем.
const outside = el('INPUT', {id: 'search'});
outside.focus();
h.keepUi(b, () => b.build());
assert.strictEqual(doc.activeElement, outside);
"""


def test_uikeep_restores_focus_and_open_details():
    node = require_node()
    res = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
