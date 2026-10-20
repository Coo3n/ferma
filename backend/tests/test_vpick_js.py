"""Выбор на снимке (vpick.js): способы словами, «найдёт N мест», лучший первым."""
import subprocess
from pathlib import Path

from _node import require_node

ROOT = Path(__file__).resolve().parents[2] / "frontend"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const STR = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const t = (k, p) => String(STR[k] ?? k).replace(/\{(\w+)\}/g, (_, n) => (p || {})[n] ?? '');
const ctx = {t, S: {}, document: {}, window: {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.h={vpParse,vpMatches,vpFriendly,vpOptions,vpShaky}', ctx);
const h = ctx.h;

const nodes = [
  {text: 'Подписаться', resourceId: 'com.vk:id/subscribe', description: '', class: 'android.widget.Button'},
  {text: 'Подписаться', resourceId: 'com.vk:id/subscribe', description: '', class: 'android.widget.Button'},
  {text: 'Войти', resourceId: 'com.vk:id/login', description: 'Login', class: 'android.widget.Button'},
];
// без жаргона: «По надписи «Войти»», «По внутреннему названию «login»»
assert.strictEqual(h.vpFriendly('text="Войти"').title, 'По надписи');
assert.strictEqual(h.vpFriendly('text="Войти"').value, 'Войти');
assert.strictEqual(h.vpFriendly('resourceId="com.vk:id/login_btn"').value, 'login btn');
assert.strictEqual(h.vpFriendly('textMatches="(?i)Разрешить"').value, 'Разрешить');
assert.ok(h.vpFriendly('text="Подписаться", instance=1').value.includes('2-й по счёту'));
// сколько мест найдёт
assert.strictEqual(h.vpMatches(nodes, 'text="Подписаться"').length, 2);
assert.strictEqual(h.vpMatches(nodes, 'text="Подписаться", instance=1').length, 1);
assert.strictEqual(h.vpMatches(nodes, 'textContains="Подпис"').length, 2);
assert.strictEqual(h.vpMatches(nodes, 'description="Login"').length, 1);
// лучший — уникальный и по надписи; «по счёту» — в конце
const opts = h.vpOptions({selectors: [
  {call: 'click', args: 'text="Подписаться", instance=0', fragile: true},
  {call: 'click', args: 'resourceId="com.vk:id/login"'},
  {call: 'click', args: 'text="Войти"'},
]}, nodes);
assert.strictEqual(opts[0].args, 'text="Войти"');
assert.strictEqual(opts[opts.length - 1].args, 'text="Подписаться", instance=0');
"""


def test_vpick_helpers():
    r = subprocess.run([require_node(), "-e", SCRIPT, str(ROOT / "js" / "vpick.js"),
                        str(ROOT / "strings" / "ru.json")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
