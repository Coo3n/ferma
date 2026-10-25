"""Пакетный ввод «каждому своё»: строка файла — на свой телефон.

Чистый модуль, как phrases.py. Зачем: у каждого телефона свой логин, свой
текст или ссылка; одинаковый текст на сорока телефонах — готовый признак
автоматизации. Режимы: по порядку (строк меньше телефонов — лишние остаются
без текста и это видно в итоге), по кругу и случайно.
"""
from __future__ import annotations

import random
import re

MAX_ROWS = 5000
MODES = ("order", "cycle", "random")
_PART = re.compile(r"\{(\d{1,2})\}")


def clean_rows(raw, limit: int = MAX_ROWS) -> list:
    """Строки без пустых; принимает текст или список строк."""
    if raw is None:
        return []
    items = raw.splitlines() if isinstance(raw, str) else [str(x) for x in raw]
    return [line.strip() for line in items if line and line.strip()][:limit]


def split_row(row: str, separator: str) -> list:
    """Строка на части по разделителю; без разделителя — одна часть."""
    if not separator:
        return [row]
    return [part.strip() for part in row.split(separator)]


def render(template: str, fields: list) -> str:
    """Шаблон «{1}@mail.ru» с частями строки; пустой шаблон — вся строка."""
    if not template:
        return " ".join(fields) if len(fields) > 1 else (fields[0] if fields else "")

    def part(match):
        n = int(match.group(1))
        return fields[n - 1] if 1 <= n <= len(fields) else ""
    return _PART.sub(part, template)


def assign(serials, rows, mode: str, rng=None) -> dict:
    """Какая строка достаётся какому телефону; None — строки не хватило."""
    if mode not in MODES:
        raise ValueError(f"режим «{mode}» неизвестен: по порядку, по кругу или случайно")
    rng = rng or random
    out = {}
    for i, serial in enumerate(serials):
        if not rows:
            out[serial] = None
        elif mode == "order":
            out[serial] = rows[i] if i < len(rows) else None
        elif mode == "cycle":
            out[serial] = rows[i % len(rows)]
        else:
            out[serial] = rng.choice(rows)
    return out
