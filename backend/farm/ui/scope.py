"""«Внутри родителя» и «рядом с элементом»: выбор цели среди одинаковых.

Лайки в ленте: id и подпись у всех одинаковые. Номер среди похожих
(`instance`) ломается, как только лента сдвинется. Устойчивее сказать, ГДЕ
искать: внутри контейнера с уникальным id (`within`) или рядом с уникальной
надписью — автором поста (`near`).

Чистые функции над узлами из farm/ui/tree.py: ни adb, ни uiautomator2. На
прогоне ctx снимает дамп и зовёт `pick`; в конструкторе ту же логику повторяет
recorder.js (recScopePick), тесты сверяют обе стороны.
"""
from __future__ import annotations

import ast
import re

from .tree import Node


class ScopeError(ValueError):
    """Селектор не разобрать или ключ не проверить по дампу."""


# Что умеет сверять pick — подмножество ключей uiautomator2, которые пишет
# панель (farm/ui/selectors.py, «свой вариант» в recorder.js).
_STR = {
    "text": lambda n, v: n.text == v,
    "textContains": lambda n, v: v in n.text,
    "textStartsWith": lambda n, v: n.text.startswith(v),
    "description": lambda n, v: n.description == v,
    "descriptionContains": lambda n, v: v in n.description,
    "descriptionStartsWith": lambda n, v: n.description.startswith(v),
    "resourceId": lambda n, v: n.resource_id == v,
    "className": lambda n, v: n.cls == v,
    "packageName": lambda n, v: n.package == v,
}
# Регулярки uiautomator2 (Java String.matches) — совпадение целиком.
_RE = {"resourceIdMatches": "resource_id", "textMatches": "text",
       "descriptionMatches": "description", "classNameMatches": "cls"}
TARGET_KEYS = frozenset(_STR) | frozenset(_RE) | {"clickable", "instance"}
# Ориентир и контейнер — только точные или частичные надписи и id: регулярка
# и номер по счёту сами по себе хрупки, на них место поиска не держится.
ANCHOR_KEYS = ("text", "textContains", "textStartsWith", "description",
               "descriptionContains", "descriptionStartsWith", "resourceId",
               "className")


def parse_args(args: str) -> dict:
    """`resourceId="a", instance=1` → словарь. Только литералы, без eval."""
    try:
        call = ast.parse(f"f({args})", mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        raise ScopeError(f"не разобрать селектор: {args}")
    if not isinstance(call, ast.Call) or call.args:
        raise ScopeError(f"не разобрать селектор: {args}")
    out = {}
    for kw in call.keywords:
        if kw.arg is None or not isinstance(kw.value, ast.Constant):
            raise ScopeError(f"не разобрать селектор: {args}")
        out[kw.arg] = kw.value.value
    return out


def _match(node: Node, sel: dict) -> bool:
    for key, value in sel.items():
        if key == "instance":
            continue
        if key in _STR:
            if not _STR[key](node, str(value)):
                return False
        elif key in _RE:
            try:
                if re.fullmatch(str(value), getattr(node, _RE[key]), re.S) is None:
                    return False
            except re.error:
                raise ScopeError(f"кривая регулярка в «{key}»: {value}")
        elif key == "clickable":
            if node.clickable != bool(value):
                return False
        else:
            raise ScopeError(f"ключ «{key}» нельзя сочетать с «внутри»/«рядом с»")
    return True


def find(nodes: list[Node], sel: dict, among=None) -> list[Node]:
    """Узлы под селектор в порядке дерева; `instance` — номер среди них."""
    pool = nodes if among is None else among
    found = [n for n in pool if _match(n, sel)]
    if "instance" in sel:
        k = int(sel["instance"])
        return found[k:k + 1] if 0 <= k < len(found) else []
    return found


def chain(nodes: list[Node], node: Node) -> list[int]:
    """Предки узла от него самого до корня (id)."""
    out = [node.id]
    while nodes[out[-1]].parent is not None:
        out.append(nodes[out[-1]].parent)
    return out


def inside(nodes: list[Node], node: Node, container: Node) -> bool:
    """Строго внутри контейнера."""
    return node.id != container.id and container.id in chain(nodes, node)


def common_depth(nodes: list[Node], a: Node, b: Node) -> int:
    """Глубина наименьшего общего предка: чем больше, тем ближе по дереву."""
    ca = chain(nodes, a)[::-1]
    cb = chain(nodes, b)[::-1]
    depth = 0
    for x, y in zip(ca, cb):
        if x != y:
            break
        depth += 1
    return depth


def _center(n: Node) -> tuple[float, float]:
    return ((n.bounds[0] + n.bounds[2]) / 2, (n.bounds[1] + n.bounds[3]) / 2)


def closest(nodes: list[Node], candidates: list[Node], anchor: Node) -> list[Node]:
    """Кандидаты по близости к ориентиру: сначала глубже общий предок
    (та же карточка поста), при равной глубине — ближе по экрану."""
    ax, ay = _center(anchor)

    def key(n):
        x, y = _center(n)
        return (-common_depth(nodes, n, anchor), (x - ax) ** 2 + (y - ay) ** 2)

    return sorted((n for n in candidates if n.id != anchor.id), key=key)


def pick(nodes: list[Node], sel: dict, within: dict | None = None,
         near: dict | None = None) -> tuple[Node | None, str]:
    """Узел для нажатия и причина промаха: "" — нашли, "within" — нет
    контейнера, "near" — нет ориентира, "target" — нет самой цели."""
    among = None
    if within:
        boxes = find(nodes, within)
        if not boxes:
            return None, "within"
        among = [n for n in nodes if inside(nodes, n, boxes[0])]
    anchor = None
    if near:
        anchors = find(nodes, near)
        if not anchors:
            return None, "near"
        anchor = anchors[0]
    found = find(nodes, sel, among)
    if anchor is not None:
        found = closest(nodes, found, anchor)
    if not found:
        return None, "target"
    return found[0], ""
