"""Карточка галереи: отрисовка, значок «не проверено», состояние «уже в моих»."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "gallery.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {
  esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'),
  t: (k, v) => k + (v ? JSON.stringify(v) : ''),
};
vm.createContext(ctx);
vm.runInContext(src + ';this.card=galleryCard', ctx);
const item = {key: 'tiktok_feed', name: 'TikTok <лента>', description: 'Листает', platform: 'TikTok',
              verified: false, package: 'com.x', added: false};
let html = ctx.card(item);
assert.ok(html.includes('TikTok &lt;лента&gt;'), 'имя экранируется');
assert.ok(html.includes('gallery.ne_proveren'), 'значок «не проверено»');
assert.ok(html.includes("galleryAdd('tiktok_feed')"), 'кнопка добавления');
assert.ok(!html.includes('gallery.uzhe_v_moih'));
html = ctx.card({...item, verified: true, added: true});
assert.ok(!html.includes('gallery.ne_proveren'));
assert.ok(html.includes('gallery.uzhe_v_moih'));
assert.ok(!html.includes("galleryAdd('tiktok_feed')"));
"""


def test_gallery_card():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
