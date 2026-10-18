"""Предпросмотр «Вставить списком» (accounts.js) обещает то же, что сделает
сервер (import_report): те же логины, прокси, дубли и строки без пароля."""
import json
import subprocess
from pathlib import Path

import pytest

from _node import require_node
from farm import accounts

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "accounts.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const ctx = {
    t: k => k, PLATFORM_NAMES: {vk: 'VK'}, S: {devices: [], view: ''},
    window: {}, document: {addEventListener() {}}, setInterval() {},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.plan=accImportPlan;this.A=ACC', ctx);
const input = JSON.parse(process.argv[2]);
ctx.A.items = input.items;
process.stdout.write(JSON.stringify(ctx.plan(input.text, 'vk')));
"""

TEXT = "\n".join([
    "Old:1",               # уже есть (регистр не важен)
    "new:2:1.2.3.4:8080",  # ok, прокси с двоеточием
    "NEW:3",               # повтор выше
    "nopass",              # без пароля
    "",
    "# комментарий",
    "semi;pw;host:1",
    "tab\tpw",
    "comma,pw",
    "a:p,w",
    "empty:",
])


@pytest.fixture
def acc_file(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(accounts, "_items", None)


def test_предпросмотр_совпадает_с_сервером(acc_file):
    node = require_node()
    accounts.create({"platform": "vk", "login": "old", "password": "x"})
    accounts.create({"platform": "tg", "login": "semi", "password": "x"})  # другая платформа
    items = [{"platform": a["platform"], "login": a["login"]} for a in accounts.all_accounts()]
    out = subprocess.run([node, "-e", SCRIPT, str(JS), json.dumps({"items": items, "text": TEXT})],
                         capture_output=True, text=True, check=True).stdout
    plan = json.loads(out)

    report = accounts.import_report(TEXT, "vk")
    ok = [r for r in plan if r["kind"] == "ok"]
    assert [r["login"] for r in ok] == [a["login"] for a in report["created"]]
    assert [r["proxy"] for r in ok] == [a["proxy"] for a in report["created"]]
    assert sum(r["kind"] == "dup" for r in plan) == report["duplicates"]
    assert [r["n"] for r in plan if r["kind"] == "bad"] == report["bad_lines"]
