"""Вторая строка карточки шага и сворачивание блоков (recorder.js) — под node."""
import json
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js"

PRELUDE = r"""
const vm = require('vm'), fs = require('fs');
const noop = () => {};
const STR = JSON.parse(fs.readFileSync(process.argv[1] + '/../strings/ru.json', 'utf8'));
const ctx = {console, localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
    document: {querySelector: () => null, addEventListener: noop, getElementById: () => null,
               readyState: 'complete'},
    setTimeout, clearTimeout, Image: function () {},
    esc: v => String(v ?? ''),
    t: (k, v) => {
        const s = STR[k];
        if (s == null) throw new Error('нет строки ' + k);
        return v ? s.replace(/\{(\w+)\}/g, (m, n) => (v[n] != null ? v[n] : m)) : s;
    }};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1] + '/recorder.js', 'utf8'), ctx, {filename: 'recorder'});
"""


def node(body: str):
    out = subprocess.run(
        [require_node(), "-e", PRELUDE + "vm.runInContext(" + json.dumps(body) + ", ctx);", str(JS)],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_вторая_строка_шага():
    got = node("""
    const s = [
      {kind: 'click', args: {}, selector: {call: 'click', args: 'text="Войти"'}},
      {kind: 'click', args: {}, selector: {call: 'click', args: 'description="Закрыть"'}},
      {kind: 'click', args: {}, crop: 'AAA'},
      {kind: 'click', args: {}, point: {x: .5, y: .5}},
      {kind: 'sleep', args: {seconds: 2, seconds_max: 5}},
      {kind: 'sleep', args: {seconds: 2}},
      {kind: 'wait', args: {timeout: 20}, any: []},
      {kind: 'wait_gone', args: {timeout: 8, on_fail: 'skip'}, any: []},
      {kind: 'key', args: {name: 'BACK'}}];
    console.log(JSON.stringify(s.map(recStepSub)));""")
    assert got == ["по тексту", "по подписи", "по картинке", "в точке", "случайная", "",
                   "до 20 с, иначе остановить", "до 8 с, иначе идти дальше", ""]


def test_чип_количества_шагов_и_категории():
    got = node("""
    console.log(JSON.stringify([1, 2, 5, 11, 21, 24].map(recStepsCount)
      .concat(['click', 'wait', 'proxy', 'type'].map(k => recCat({kind: k})))));""")
    assert got == ["1 шаг", "2 шага", "5 шагов", "11 шагов", "21 шаг", "24 шага",
                   "act", "wait", "sys", "plain"]
