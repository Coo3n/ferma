"""Proxy credentials are masked: the list shows only the address."""
import json
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "accounts.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const ctx = {t: k => k, PLATFORM_NAMES: {vk: 'VK'}, S: {devices: [], view: ''},
    window: {}, document: {addEventListener() {}}, setInterval() {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + ';this.s=accProxySecret;this.h=accProxyHost', ctx);
const cases = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(cases.map(p => [ctx.s(p), ctx.h(p)])));
"""


def test_proxy_secret_and_host():
    node = require_node()
    cases = ["", "1.2.3.4:8080", "user:pw@1.2.3.4:8080", "http://u:p@h.io:3128",
             "1.2.3.4:8080:user:pw"]
    out = subprocess.run([node, "-e", SCRIPT, str(JS), json.dumps(cases)],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [
        [False, ""], [False, "1.2.3.4:8080"], [True, "1.2.3.4:8080"],
        [True, "h.io:3128"], [True, "1.2.3.4:8080"],
    ]
