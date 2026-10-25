"""Монитор уведомлений: что пришло в шторку телефонов, без открытия экранов.

Читается `dumpsys notification --noredact` — только шторка, содержимое
приложений недоступно (и не должно быть). Формат вывода зависит от версии
Android, поэтому разбор терпимый: нераспознанное пропускается, а не падает.
Текст уведомлений по умолчанию скрыт, а у банков и приложений с кодами он не
показывается никогда: код подтверждения не должен светиться в списке.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import adb, config

_REC = re.compile(r"NotificationRecord\(0x[0-9a-f]+: pkg=([\w.]+) ")
_FLAGS = re.compile(r"flags=0x([0-9a-f]+)")
_TITLE = re.compile(r"android\.title=(?:[A-Za-z]+ )?\((.*)\)\s*$", re.M)
_TEXT = re.compile(r"android\.text=(?:[A-Za-z]+ )?\((.*)\)\s*$", re.M)
_PKG = re.compile(r"^[A-Za-z][\w]*(\.[\w]+)+$")
_SECRET = re.compile(r"(bank|sber|tinkoff|vtb|alfa|raiffeisen|gazprom|pay|wallet|authenticator|otp|2fa)", re.I)
# Постоянные уведомления (FLAG_ONGOING_EVENT, FLAG_FOREGROUND_SERVICE) — не
# «новое сообщение», а работающая служба; в сводке они только мешают.
_ONGOING = 0x2 | 0x40
DUMP_CMD = "dumpsys notification --noredact"


@dataclass
class Note:
    pkg: str
    title: str
    text: str


def parse(out) -> list:
    text = out or ""
    starts = [(m.start(), m.group(1)) for m in _REC.finditer(text)]
    notes = []
    for i, (pos, pkg) in enumerate(starts):
        block = text[pos: starts[i + 1][0] if i + 1 < len(starts) else len(text)]
        flags = _FLAGS.search(block)
        if flags and int(flags.group(1), 16) & _ONGOING:
            continue
        title, body = _TITLE.search(block), _TEXT.search(block)
        notes.append(Note(pkg, title.group(1).strip() if title else "",
                          body.group(1).strip() if body else ""))
    return notes


def is_secret(pkg: str) -> bool:
    return bool(_SECRET.search(pkg or ""))


def watched() -> list:
    try:
        data = json.loads(config.NOTIFY_WATCH_FILE.read_text("utf-8"))
        return [p for p in data.get("packages", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def set_watched(packages) -> list:
    clean = []
    for p in packages or []:
        p = str(p).strip()
        if _PKG.match(p) and p not in clean:
            clean.append(p)
    config.NOTIFY_WATCH_FILE.write_text(json.dumps({"packages": clean}, ensure_ascii=False), "utf-8")
    return clean


def scan_phone(serial: str, packages, show_text: bool) -> dict:
    notes = parse(adb.shell(serial, DUMP_CMD, timeout=15))
    if packages:
        notes = [n for n in notes if n.pkg in packages]
    items = []
    for n in notes:
        item = {"pkg": n.pkg}
        if show_text and not is_secret(n.pkg):
            item.update(title=n.title, text=n.text)
        items.append(item)
    return {"count": len(items), "items": items}
