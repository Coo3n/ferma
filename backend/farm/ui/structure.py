"""Элементы экрана по структуре, а не по resource-id.

У TikTok id меняются между версиями, а раскладка держится дольше: справа
колонка из пяти значков, внизу панель из пяти вкладок. Скрипт Laixi ищет
элементы именно так. Чистые функции над узлами farm/ui/tree.py: ни adb, ни
uiautomator2, проверяются на образцах дампа.
"""
from __future__ import annotations

from .tree import Node


def center(node: Node):
    """Центр рамки в долях экрана — то, что принимает ctx.tap."""
    x0, y0, x1, y1 = node.bounds
    return (x0 + x1) / 2, (y0 + y1) / 2


def _is(node: Node, name: str) -> bool:
    return node.cls.endswith(name)


def action_column(nodes):
    """Правая колонка действий: LinearLayout с ≥5 детьми, высокий и у правого края.

    Дети сверху вниз: аватар (с «+» подписки), лайк, комментарий, избранное,
    «поделиться». Нет колонки (видео не открыто, реклама) — пустой список.
    """
    best = None
    for node in nodes:
        if not _is(node, "LinearLayout") or len(node.children) < 5:
            continue
        cx, _ = center(node)
        height = node.bounds[3] - node.bounds[1]
        if cx < 0.75 or height < 0.25:
            continue
        if best is None or node.area > best.area:
            best = node
    if best is None:
        return []
    return sorted((nodes[c] for c in best.children), key=lambda n: (n.bounds[1], n.bounds[0]))


def follow_plus(nodes, column):
    """Значок «+» подписки: второй ребёнок внутри первого элемента колонки.
    Нет его или он не нажимается (уже подписан) — None."""
    if not column or not column[0].children:
        return None
    inner = nodes[column[0].children[0]]
    if len(inner.children) < 2:
        return None
    plus = nodes[inner.children[1]]
    return plus if plus.clickable else None


def tab_bar(nodes):
    """Нижняя панель: LinearLayout ровно из пяти вкладок у нижнего края."""
    for node in nodes:
        if _is(node, "LinearLayout") and len(node.children) == 5 and node.bounds[1] >= 0.9:
            return sorted((nodes[c] for c in node.children), key=lambda n: n.bounds[0])
    return []


def grid_tiles(nodes):
    """Плитки результатов поиска: нажимаемый FrameLayout с ≥2 детьми, у второго
    есть свои дети. Порядок чтения: сверху вниз, слева направо."""
    tiles = []
    for node in nodes:
        if not (_is(node, "FrameLayout") and node.clickable and len(node.children) > 1):
            continue
        if node.bounds[1] < 0.1 or not nodes[node.children[1]].children:
            continue
        tiles.append(node)
    return sorted(tiles, key=lambda n: (round(n.bounds[1], 2), n.bounds[0]))


def send_after_input(nodes):
    """Кнопка отправки комментария: последний ребёнок родителя поля ввода.
    Поле одно в родителе или поля нет — None."""
    for node in nodes:
        if not _is(node, "EditText") or node.parent is None:
            continue
        parent = nodes[node.parent]
        last = nodes[parent.children[-1]]
        return None if last.id == node.id else last
    return None
