"""Всё, что панель умеет написать в селектор, проходит normalize_target.

Иначе человек нажмёт «повторить» с целью, собранной самой панелью, и получит
400. Проверяем и Python-путь (selectors.py, obstacle.py, codegen), и разбор
строки пикером в браузере (repairParseSel под node).
"""
import json
import re

import pytest

from _node import require_node
from farm import obstacle
from farm.context import normalize_target
from farm.recorder import codegen, steps
from farm.ui import selectors, tree

XML = ('<hierarchy>'
       '<node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">'
       '<node class="android.widget.Button" text="Войти в аккаунт 12" resource-id="a:id/go" '
       'content-desc="Вход" clickable="true" bounds="[0,0][100,100]"/>'
       '<node class="android.widget.Button" text="Войти в аккаунт 12" resource-id="a:id/go" '
       'content-desc="Вход" clickable="true" bounds="[0,110][100,200]"/>'
       '<node class="android.widget.ImageView" clickable="true" bounds="[0,210][100,300]"/>'
       '<node class="android.widget.ImageView" clickable="true" bounds="[0,310][100,400]"/>'
       '</node></hierarchy>')


def _panel_args():
    """Все строки args, которые панель отдаёт пикеру (включая instance/className)."""
    nodes = tree.parse(XML, 1080, 2400)
    out = []
    for node in nodes:
        for c in selectors.build_selectors(nodes, node):
            if c["call"] == "click":
                out.append(c["args"])
    return out


def _dict(args):
    return eval("dict(" + args + ")", {"dict": dict})


def test_панель_даёт_разные_формы():
    keys = {k for a in _panel_args() for k in _dict(a)}
    assert {"resourceId", "description", "text", "className", "instance"} <= keys


def test_селекторы_панели_проходят():
    for args in _panel_args():
        assert normalize_target({"sel": [_dict(args)]})


def test_шаг_с_запасными_и_instance_рендерится_в_принимаемый_sel():
    step = steps.normalize_step({
        "kind": "click", "args": {}, "texts": ["Войти"], "point": [0.5, 0.5],
        "selector": {"call": "click", "args": 'text="Войти"',
                     "fallbacks": ['resourceId="a:id/go", className="x.Y"',
                                   'className="android.widget.Button", instance=1',
                                   'textContains="Войти"']}})
    src = codegen.render({"name": "t", "description": "", "watch_popups": False}, {}, [step])
    m = re.search(r"sel=\[(.*?)\](?=, text=)", src)
    chain = [eval(x, {"dict": dict}) for x in re.findall(r"dict\(.*?\)(?=, dict\(|$)", m.group(1))]
    assert len(chain) == 4
    assert normalize_target({"sel": chain})["sel"] == chain


def test_кандидаты_преграды_проходят():
    xml = ('<hierarchy><node class="a.B" text="Обновить приложение" '
           'resource-id="a:id/upd" content-desc="Диалог обновления" '
           'bounds="[0,0][500,500]"/></hierarchy>')
    cand = obstacle.capture(xml, 1080, 2400, "a")
    assert cand and cand["candidates"]
    for c in cand["candidates"]:
        assert normalize_target({"sel": [c["selector"]]})


def test_пикер_разбирает_строки_панели_в_принимаемые_словари():
    node = require_node()
    import subprocess
    from pathlib import Path
    js = Path(__file__).resolve().parents[2] / "frontend" / "js"
    args = _panel_args()
    prog = r"""
    const vm = require('vm'), fs = require('fs');
    const noop = () => {};
    const ctx = {console, localStorage: {getItem: () => null, setItem: noop, removeItem: noop},
        document: {querySelector: () => null, addEventListener: noop, getElementById: () => null,
                   readyState: 'complete'}, setTimeout, clearTimeout, Image: function () {}};
    ctx.window = ctx; vm.createContext(ctx);
    for (const f of ['recorder', 'repair'])
        vm.runInContext(fs.readFileSync(process.argv[1] + '/' + f + '.js', 'utf8'), ctx, {filename: f});
    ctx.p = vm.runInContext('repairParseSel', ctx);
    const inp = JSON.parse(process.argv[2]);
    console.log(JSON.stringify(inp.map(a => ctx.p(a))));
    """
    r = subprocess.run([node, "-e", prog, str(js), json.dumps(args)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    parsed = json.loads(r.stdout)
    assert len(parsed) == len(args)
    for a, d in zip(args, parsed):
        assert d == _dict(a)
        assert normalize_target({"sel": [d]})
