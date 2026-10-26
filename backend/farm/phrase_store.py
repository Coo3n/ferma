"""Группы быстрых фраз: очистка, лимиты, импорт и экспорт.

Разбор и очистка работают с обычными словарями; с диском связаны только
`load` и `save` (файл config.PHRASES_FILE, запись атомарная).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import secrets
import threading
from pathlib import Path

from . import config

log = logging.getLogger("farm.phrases")

MAX_GROUPS = 30
MAX_ITEMS = 100
MAX_PHRASE = 500
MAX_NAME = 40
DEFAULT_NAME = "Общие"

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
_lock = threading.RLock()


def _new_id(used: set) -> str:
    while True:
        gid = secrets.token_hex(4)
        if gid not in used:
            return gid


def _items(raw) -> list:
    out, seen = [], set()
    for x in raw if isinstance(raw, list) else []:
        if not isinstance(x, str):
            continue
        s = x.strip()[:MAX_PHRASE].strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= MAX_ITEMS:
            break
    return out


def clean(data) -> dict:
    """Привести любую структуру к допустимой: лимиты, дубли, активная группа."""
    groups, used = [], set()
    raw = data.get("groups") if isinstance(data, dict) else None
    for g in raw if isinstance(raw, list) else []:
        if not isinstance(g, dict):
            continue
        if len(groups) >= MAX_GROUPS:
            break
        gid = g.get("id")
        if not (isinstance(gid, str) and _ID_RE.match(gid)) or gid in used:
            gid = _new_id(used)
        used.add(gid)
        name = g.get("name")
        name = name.strip()[:MAX_NAME].strip() if isinstance(name, str) else ""
        groups.append({"id": gid, "name": name or "Группа", "items": _items(g.get("items"))})
    if not groups:
        groups = [{"id": _new_id(used), "name": DEFAULT_NAME, "items": []}]
    active = data.get("active") if isinstance(data, dict) else None
    if active not in {g["id"] for g in groups}:
        active = groups[0]["id"]
    return {"groups": groups, "active": active}


def _find(data: dict, group_id):
    gid = group_id or data["active"]
    for g in data["groups"]:
        if g["id"] == gid:
            return g
    raise ValueError("нет такой группы")


def _first_column(line: str) -> str:
    delim = next((d for d in (";", "\t", ",") if d in line), None)
    if delim is None:
        return line.strip()
    try:
        row = next(csv.reader([line], delimiter=delim))
    except (csv.Error, StopIteration):
        row = [line.split(delim)[0]]
    return row[0].strip() if row else ""


def import_text(data: dict, group_id, text: str, csv: bool = False) -> dict:
    """Добавить фразы из текста (по строке на фразу) в группу; вернуть новую
    очищенную структуру. Для csv берётся первый столбец (; , или табуляция)."""
    out = clean(json.loads(json.dumps(data)))
    group = _find(out, group_id)
    lines = (text or "").lstrip("﻿").splitlines()
    new = [_first_column(ln) if csv else ln.strip() for ln in lines]
    group["items"] = group["items"] + [p for p in new if p]
    return clean(out)


def export_csv(data: dict, group_id=None) -> bytes:
    """Фразы группы в UTF-8 с BOM, по одной в строке (csv, один столбец)."""
    group = _find(clean(data), group_id)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for p in group["items"]:
        w.writerow([p])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


def load() -> dict:
    try:
        raw = json.loads(Path(config.PHRASES_FILE).read_text("utf-8"))
    except FileNotFoundError:
        raw = None
    except (OSError, ValueError) as e:
        log.warning("файл фраз не читается (%s) — значения по умолчанию", e)
        raw = None
    return clean(raw)


def save(data) -> dict:
    out = clean(data)
    path = Path(config.PHRASES_FILE)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
    return out
