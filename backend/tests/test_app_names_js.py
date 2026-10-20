"""Имена приложений по пакету (recorder.js: recApp): бренд не должен быть именем."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "recorder.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('const REC_APPS'), b = src.indexOf('const REC_KEYS');
const c = src.indexOf('const REC_PKG_NOISE'), d = src.indexOf('/* Автоимя экрана');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + src.slice(c, d) + ';this.app=recApp', ctx);
const app = ctx.app;
assert.strictEqual(app('com.vkontakte.android'), '«VK»');
assert.strictEqual(app('com.samsung.android.app.notes'), '«Notes»');
assert.strictEqual(app('com.sec.android.app.camera'), '«Camera»');
assert.strictEqual(app('com.samsung.android.messaging'), '«Messaging»');
assert.strictEqual(app('com.google.android.apps.maps'), '«Maps»');
assert.strictEqual(app('com.example.app.dev'), '«Example»');
assert.notStrictEqual(app('com.samsung.android.dialer'), app('com.samsung.android.calendar'));
// Разные приложения одной компании не сливаются в одно «Yandex».
assert.strictEqual(app('com.yandex.music'), '«Yandex Music»');
assert.strictEqual(app('ru.yandex.searchplugin'), '«Yandex Searchplugin»');
assert.strictEqual(app('ru.yandex.yandexmaps'), '«Yandex Maps»');
"""


def test_app_names():
    r = subprocess.run([require_node(), "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
