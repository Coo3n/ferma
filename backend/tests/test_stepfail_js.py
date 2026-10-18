"""«Если не нашёл» (stepfail.js) раскладывается на optional/retries шага."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "stepfail.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8')
    + ';this.h={stFailGet,stFailSet,ST_FAIL_TRIES}', ctx);
const h = ctx.h;
const plain = v => JSON.parse(JSON.stringify(v));

assert.deepStrictEqual(plain(h.stFailGet({})), {tries: 1, skip: false});
assert.deepStrictEqual(plain(h.stFailGet({retries: 2, optional: true})), {tries: 3, skip: true});

const s = {kind: 'click'};
h.stFailSet(s, {tries: 3, skip: true});
assert.deepStrictEqual(plain(s), {kind: 'click', retries: 2, optional: true});
h.stFailSet(s, {tries: 1, skip: false});
assert.deepStrictEqual(plain(s), {kind: 'click'});
h.stFailSet(s, {tries: 99});
assert.strictEqual(s.retries, 5);
h.stFailSet(s, {tries: 'мусор'});
assert.strictEqual('retries' in s, false);
assert.ok(h.ST_FAIL_TRIES.includes(1) && h.ST_FAIL_TRIES.every(n => n >= 1 && n <= 6));
"""


def test_stepfail_mapping():
    node = require_node()
    res = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
