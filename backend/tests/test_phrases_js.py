"""phrases.js — тот же разбор вариантов, что в farm/phrases.py.

Два разбора в двух языках расходятся молча: конструктор обещает «один из
трёх», телефон отправляет скобки. Поэтому обе реализации гоняются на одних
входах и сверяются числом вариантов и признаком «надо разворачивать».
"""
import json
import subprocess
from pathlib import Path

from _node import require_node

from farm import phrases

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "phrases.js"

CASES = [
    "", "привет", "{}", "{один}", '{"a": 1}', "a|b", "цена 5}",
    "{привет|здравствуй}", "{привет|хай}, {друг|дружище}", "{a|{b|c}}",
    "{привет|добрый {день|вечер}}", "{привет|здравствуй",
    r"цена \{5\}", r"\{a\|b\}", r"{a\|b|c}", "{a|b}" * 40,
]

SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8')
    + ';this.go = t => [phrCount(t), phrPick(t) === t]', ctx);
const out = JSON.parse(process.argv[2]).map(t => ctx.go(t));
console.log(JSON.stringify(out));
"""


def test_js_matches_python():
    require_node()
    got = subprocess.run(["node", "-e", SCRIPT, "--", str(JS), json.dumps(CASES)],
                         capture_output=True, text=True, check=True)
    for text, (count, как_есть) in zip(CASES, json.loads(got.stdout)):
        assert count == phrases.count(text), text
        # «текст не изменился» — тот же ответ, что у pick в питоне
        assert как_есть == (phrases.pick(text) == text), text


def test_js_pick_stays_inside_the_variants():
    require_node()
    script = SCRIPT.replace("[phrCount(t), phrPick(t) === t]",
                            "Array.from({length: 40}, () => phrPick(t))")
    got = subprocess.run(["node", "-e", script, "--", str(JS),
                          json.dumps(["{привет|здравствуй|хай}", r"{скидка \{5\}|даром}"])],
                         capture_output=True, text=True, check=True)
    варианты, экран = json.loads(got.stdout)
    assert set(варианты) == {"привет", "здравствуй", "хай"}
    assert set(экран) == {"скидка {5}", "даром"}
