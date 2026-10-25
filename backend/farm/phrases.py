"""Варианты текста: «{привет|здравствуй}» → одно из на каждом прогоне.

Зачем. Сорок телефонов, отправивших байт в байт один и тот же комментарий,
— это готовый признак автоматизации: искать такое куда проще, чем разбирать
поведение. Джиттер разносит действия по времени, но текст оставляет
одинаковым, поэтому вариант выбирается здесь, на каждом телефоне свой.

Модуль чистый: ни adb, ни диска, ни FastAPI — как ui/tree.py (см.
docs/GOTCHAS.md). Разбор никогда не падает: «{» без закрывающей скобки
остаётся обычным текстом, а не роняет сценарий на живом телефоне.
"""
from __future__ import annotations

import random

# Глубже этого вложенность перестаёт читаться человеком, а фигурная скобка
# снова становится обычным символом.
MAX_DEPTH = 4
# Потолок на подсчёт комбинаций: число нужно только чтобы показать его
# человеку («один из 12»), и перемножать до переполнения незачем.
COUNT_MAX = 100000
SPECIAL = "{}|\\"


def _parse_seq(text: str, i: int, depth: int, inner: bool):
    """Последовательность: куски текста и группы вариантов между ними.

    `inner` — разбор идёт внутри группы, значит «|» и «}» её закрывают.
    Возвращает (список узлов, позиция). Узел — строка или список
    альтернатив, каждая из которых сама такая же последовательность.
    """
    parts: list = []
    buf: list[str] = []
    while i < len(text):
        ch = text[i]
        # Экранирование: «\{» — это именно скобка в тексте, а не группа.
        if ch == "\\" and i + 1 < len(text) and text[i + 1] in SPECIAL:
            buf.append(text[i + 1])
            i += 2
            continue
        if inner and ch in "|}":
            break
        if ch == "{" and depth < MAX_DEPTH:
            alts, j = _parse_group(text, i, depth)
            if alts is not None:
                if buf:
                    parts.append("".join(buf))
                    buf = []
                parts.append(alts)
                i = j
                continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts, i


def _parse_group(text: str, i: int, depth: int):
    """Группа «{a|b}» с позиции i. (None, i) — это не группа, а просто текст.

    Не группой считаются два случая, и оба нарочно: незакрытая скобка (текст
    человек писал руками, и терять его хвост нельзя) и «{одно}» без «|» —
    иначе фигурные скобки нельзя было бы написать в тексте вообще.
    """
    alts: list = []
    j = i + 1
    while True:
        seq, j = _parse_seq(text, j, depth + 1, True)
        alts.append(seq)
        if j >= len(text):
            return None, i
        if text[j] == "|":
            j += 1
            continue
        j += 1          # text[j] == "}"
        break
    if len(alts) < 2:
        return None, i
    return alts, j


def parse(text: str) -> list:
    """Текст → дерево. Публична ради тестов и count/pick."""
    return _parse_seq(str(text or ""), 0, 0, False)[0]


def _count(parts: list) -> int:
    total = 1
    for part in parts:
        if isinstance(part, str):
            continue
        total *= sum(_count(alt) for alt in part)
        if total >= COUNT_MAX:
            return COUNT_MAX
    return total


def count(text: str) -> int:
    """Сколько разных текстов может получиться. 1 — вариантов нет."""
    return _count(parse(text))


def _build(parts: list, rnd) -> str:
    out = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        else:
            out.append(_build(rnd.choice(part), rnd))
    return "".join(out)


def pick(text: str, rnd=None) -> str:
    r"""Один из вариантов. Вариантов нет — текст как есть, байт в байт.

    Экранирование («\{» → «{») снимается только у текста с вариантами: оно и
    нужно лишь затем, чтобы написать скобку рядом с ними. Текст без
    вариантов не меняется вообще — иначе «C:\\папка», набранный человеком в
    поле, молча терял бы слеш.
    """
    text = str(text or "")
    parts = parse(text)
    if not any(isinstance(p, list) for p in parts):
        return text
    return _build(parts, rnd or random)


def _bare(text: str) -> str:
    """Текст без экранированных символов — чтобы «\\|» не считалось за «|»."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in SPECIAL:
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def check(text: str) -> str:
    """Предупреждение для человека, или «» если всё в порядке.

    Ловит ровно одну ошибку, зато самую частую: человек написал варианты, но
    забыл закрыть скобку — текст уйдёт на телефон вместе со скобками, и
    заметит он это уже по результату.
    """
    text = str(text or "")
    if not text or count(text) > 1:
        return ""
    bare = _bare(text)
    if "{" in bare and "|" in bare:
        return ("похоже на варианты текста, но фигурная скобка не закрыта — "
                "пишите так: {привет|здравствуй}")
    return ""
