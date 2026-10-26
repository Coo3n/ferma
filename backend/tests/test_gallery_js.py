"""Галерея: поиск, платформы, карточка (экранирование, бейджи, шаги, «уже в моих»)."""
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
vm.runInContext(src + ';this.card=galleryCard;this.filter=galleryFilter;this.plats=galleryPlatforms;this.tone=galleryTone', ctx);
const plain = x => JSON.parse(JSON.stringify(x));

const item = {key: 'tiktok_feed', name: 'TikTok <лента>', description: 'Листает', platform: 'TikTok',
              verified: false, package: 'com.x', added: false, kind: 'code', editable: false,
              steps_text: [{text: 'Открыть <приложение>', depth: 0}, {text: 'Лайкнуть', depth: 2}],
              params: [{name: 'n', label: 'Сколько <раз>'}]};

// --- карточка
let html = ctx.card(item, {});
assert.ok(html.includes('TikTok &lt;лента&gt;'), 'имя экранируется');
assert.ok(!html.includes('<лента>'));
assert.ok(html.includes('gallery.ne_proveren'), 'бейдж «не проверено»');
assert.ok(html.includes('gallery.tolko_parametry'), 'код — только параметры');
assert.ok(!html.includes('gallery.pravitsya</span>'), 'не «правится»');
assert.ok(html.includes("galleryAdd('tiktok_feed')"), 'кнопка добавления');
assert.ok(html.includes('class="sm primary"'), 'добавление — основная');
assert.ok(!html.includes('gallery.uzhe_otkryt'));
assert.ok(html.includes('Открыть &lt;приложение&gt;'), 'шаги экранируются');
assert.ok(html.includes('--d:2'), 'отступ по depth');
assert.ok(html.includes('Сколько &lt;раз&gt;'), 'метки полей экранируются');
assert.ok(html.includes('aria-expanded="false"'));
assert.ok(html.includes('data-open="0"'));
assert.ok(html.includes('tabindex="-1"'));

html = ctx.card(item, {open: true, focus: true});
assert.ok(html.includes('aria-expanded="true"') && html.includes('data-open="1"'));
assert.ok(html.includes('tabindex="0"'));

html = ctx.card({...item, verified: true, added: true, editable: true, kind: 'recipe'}, {});
assert.ok(!html.includes('gallery.ne_proveren'));
assert.ok(html.includes('gallery.pravitsya</span>'));
assert.ok(html.includes('gallery.uzhe_otkryt'));
assert.ok(html.includes("galleryOpenMine('tiktok_feed')"));
assert.ok(!html.includes("galleryAdd('tiktok_feed')"));

html = ctx.card({...item, steps_text: [], params: []}, {});
assert.ok(!html.includes('gal-what') && !html.includes('gal-params'), 'без шагов и полей блоков нет');

html = ctx.card({...item, key: 'a"b'}, {busy: true});
assert.ok(!html.includes('a"b'), 'ключ экранируется');
assert.ok(html.includes('disabled'), 'во время добавления кнопка выключена');

// --- поиск и платформы
const items = [
  {key: 'a', name: 'Автолистание', description: 'Листает ленту', platform: 'YouTube',
   steps_text: [{text: 'Провести вверх', depth: 0}], params: [{name: 'n', label: 'Сколько повторов'}]},
  {key: 'b', name: 'Лента VK', description: 'Лайки', platform: 'VK', steps_text: [], params: []},
  {key: 'c', name: 'Шортсы', description: 'Короткие видео', platform: 'YouTube', steps_text: [], params: []},
];
const keys = r => r.map(i => i.key).join('');
assert.strictEqual(keys(ctx.filter(items, '', '')), 'abc');
assert.strictEqual(keys(ctx.filter(items, '  ', null)), 'abc');
assert.strictEqual(keys(ctx.filter(items, 'ЛЕНТ', '')), 'ab', 'без учёта регистра, по имени и описанию');
assert.strictEqual(keys(ctx.filter(items, 'вверх', '')), 'a', 'по шагам');
assert.strictEqual(keys(ctx.filter(items, 'повторов', '')), 'a', 'по меткам полей');
assert.strictEqual(keys(ctx.filter(items, 'ленту youtube', '')), 'a', 'все слова обязательны');
assert.strictEqual(keys(ctx.filter(items, '', 'YouTube')), 'ac');
assert.strictEqual(keys(ctx.filter(items, 'лайки', 'YouTube')), '');
assert.strictEqual(keys(ctx.filter(null, 'x', '')), '');
assert.deepStrictEqual(plain(ctx.plats(items)), [['VK', 1], ['YouTube', 2]]);
assert.deepStrictEqual(plain(ctx.plats([])), []);
assert.deepStrictEqual(plain(ctx.plats([{platform: ''}, {}])), []);
assert.strictEqual(ctx.tone('VK'), ctx.tone('VK'), 'цвет платформы стабилен');
"""


def test_gallery_js():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
