"""Ресурс строк сайта (frontend/strings/ru.json) сходится с разметкой и кодом.

Ключ, которого нет в ru.json, на экране превратился бы в «fleet.vybrat_vse»;
текст в разметке, разошедшийся с ru.json, вводил бы в заблуждение того, кто
правит index.html; лишняя строка — мусор, который все боятся удалить.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

FRONT = Path(__file__).resolve().parents[2] / "frontend"
STRINGS = json.loads((FRONT / "strings" / "ru.json").read_text("utf-8"))
HTML = (FRONT / "index.html").read_text("utf-8")
ATTRS = ("title", "placeholder", "aria-label", "alt")


class Разметка(HTMLParser):
    """Ключи из data-t* и запасной текст, который стоит рядом с ними."""

    def __init__(self):
        super().__init__()
        self.keys = {}        # ключ -> запасной текст в разметке
        self.stack = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for a in ATTRS:
            if f"data-t-{a}" in d:
                self.keys[d[f"data-t-{a}"]] = (d.get(a) or "").strip()
        if tag not in ("input", "img", "br", "meta", "link"):
            self.stack.append([d.get("data-t"), ""])

    def handle_endtag(self, tag):
        if self.stack:
            key, text = self.stack.pop()
            if key:
                self.keys.setdefault(key, " ".join(text.split()))

    def handle_data(self, data):
        if self.stack and self.stack[-1][0] and not self.stack[-1][1].strip():
            self.stack[-1][1] = data


def _html_keys():
    p = Разметка()
    p.feed(HTML)
    return p.keys


def _js_keys():
    keys = set()
    for js in (FRONT / "js").glob("*.js"):
        keys |= set(re.findall(r"\bt\('([a-z_]+\.[a-z0-9_]+)'", js.read_text("utf-8")))
    return keys


def test_ключи_разметки_есть_в_ru_json():
    missing = sorted(k for k in _html_keys() if k not in STRINGS)
    assert not missing, f"нет в strings/ru.json: {missing}"


def test_ключи_js_есть_в_ru_json():
    missing = sorted(k for k in _js_keys() if k not in STRINGS)
    assert not missing, f"нет в strings/ru.json: {missing}"


def test_запасной_текст_разметки_совпадает_с_ru_json():
    differ = {k: (v, STRINGS[k]) for k, v in _html_keys().items()
              if k in STRINGS and v and v != STRINGS[k]}
    assert not differ, f"текст в index.html разошёлся с ru.json: {differ}"


def test_в_ru_json_нет_лишних_строк():
    used = set(_html_keys()) | _js_keys()
    unused = sorted(set(STRINGS) - used)
    assert not unused, f"строки нигде не используются: {unused}"


def test_ключи_по_правилу_раздел_точка_имя():
    bad = [k for k in STRINGS if not re.fullmatch(r"[a-z]+\.[a-z0-9_]+", k)]
    assert not bad, bad
