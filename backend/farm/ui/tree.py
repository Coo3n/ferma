"""Разбор XML-дампа uiautomator в плоское дерево узлов.

На входе строка XML и размеры экрана, на выходе список узлов с координатами
в долях экрана. Модуль не обращается к adb — см. docs/GOTCHAS.md.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


class InspectError(RuntimeError):
    """Дамп не удалось разобрать."""


@dataclass
class Node:
    id: int
    parent: int | None
    bounds: tuple[float, float, float, float]
    text: str
    resource_id: str
    description: str
    cls: str
    clickable: bool
    children: list[int] = field(default_factory=list)
    package: str = ""
    # Поле ввода: пароль ли (маскируется), в фокусе ли и его подсказка —
    # по ним запись понимает, что вводят логин/пароль, и берёт его из аккаунта.
    password: bool = False
    focused: bool = False
    hint: str = ""
    # Доступен ли элемент: в отпечатке экрана «кнопка серая» и «кнопка живая» —
    # разные состояния. По умолчанию True, чтобы чужие конструкторы Node не ломались.
    enabled: bool = True
    # Переключатель/галочка: тап по нему меняет только своё состояние, и «ничего
    # не изменилось» для такого узла не повод повторять нажатие.
    checkable: bool = False

    @property
    def area(self) -> float:
        return (self.bounds[2] - self.bounds[0]) * (self.bounds[3] - self.bounds[1])


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def parse_bounds(raw, width: int, height: int):
    """`[x1,y1][x2,y2]` в пикселях → доли 0..1. None, если рамка негодная."""
    match = _BOUNDS_RE.fullmatch(raw or "")
    if match is None:
        return None
    x1, y1, x2, y2 = (int(v) for v in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return (
        _clamp(x1 / width), _clamp(y1 / height),
        _clamp(x2 / width), _clamp(y2 / height),
    )


def parse(xml: str, width: int, height: int) -> list[Node]:
    """XML-дамп → плоский список узлов, где `nodes[i].id == i`.

    Узлы с негодными рамками выбрасываются, их дети подцепляются к ближайшему
    уцелевшему предку.
    """
    if width <= 0 or height <= 0:
        raise InspectError(f"некорректный размер экрана: {width}x{height}")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise InspectError(f"не удалось разобрать XML-дамп: {e}") from e

    nodes: list[Node] = []

    def walk(element, parent_id) -> None:
        bounds = parse_bounds(element.get("bounds"), width, height)
        own_id = parent_id
        if bounds is not None:
            own_id = len(nodes)
            nodes.append(Node(
                id=own_id,
                parent=parent_id,
                bounds=bounds,
                text=(element.get("text") or "").strip(),
                resource_id=(element.get("resource-id") or "").strip(),
                description=(element.get("content-desc") or "").strip(),
                cls=(element.get("class") or "").strip(),
                clickable=element.get("clickable") == "true",
                package=(element.get("package") or "").strip(),
                password=element.get("password") == "true",
                focused=element.get("focused") == "true",
                hint=(element.get("hint") or "").strip(),
                checkable=element.get("checkable") == "true",
                enabled=element.get("enabled") != "false",
            ))
            if parent_id is not None:
                nodes[parent_id].children.append(own_id)
        for child in element:
            walk(child, own_id)

    walk(root, None)
    return nodes


def node_at(nodes: list[Node], x: float, y: float):
    """Наименьший по площади узел, накрывающий точку. Координаты в долях."""
    best = None
    for node in nodes:
        x1, y1, x2, y2 = node.bounds
        if x < x1 or x > x2 or y < y1 or y > y2:
            continue
        # <=: при равной площади — более поздний в дампе (вложенный с теми же
        # рамками или нарисованный поверх), как recHit в recorder.js.
        if best is None or node.area <= best.area:
            best = node
    return best


# ---------------------------------------------------------- тап мимо перекрывашки

def _intersects(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _contains(box, x: float, y: float) -> bool:
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def coverers(nodes: list[Node], node: Node) -> list[Node]:
    """Кликабельные соседи, которые перекрывают рамку узла.

    В дампе uiautomator нет drawingOrder, но порядок детей одного родителя
    совпадает с порядком отрисовки: поздний рисуется поверх раннего. Поэтому
    «доказанное» перекрытие — только поздний кликабельный брат с пересекающейся
    рамкой. Чужие ветки дерева не трогаем: по ним порядок не доказан.
    """
    if node.parent is None:
        return []
    out = []
    for sid in nodes[node.parent].children:
        if sid <= node.id:
            continue
        other = nodes[sid]
        if other.clickable and _intersects(node.bounds, other.bounds):
            out.append(other)
    return out


def tap_point(node: Node, over: list[Node]):
    """Куда тапать узел, у которого есть перекрывающие соседи (`coverers`).

    Центр свободен — он и есть. Перекрыт — центр крупнейшего непокрытого
    куска рамки. Свободного куска нет — None: вызывающий берёт обычный центр,
    лучше честный тап в центр, чем в случайный пиксель на краю.
    """
    x1, y1, x2, y2 = node.bounds
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    boxes = [o.bounds for o in over if _intersects(node.bounds, o.bounds)]
    if not any(_contains(b, cx, cy) for b in boxes):
        return (cx, cy)
    xs = sorted({x1, x2, *(min(max(b[i], x1), x2) for b in boxes for i in (0, 2))})
    ys = sorted({y1, y2, *(min(max(b[i], y1), y2) for b in boxes for i in (1, 3))})
    best, best_area = None, 1e-5      # мельче ~0.3% экрана по стороне не тапнуть
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            ax, bx, ay, by = xs[i], xs[i + 1], ys[j], ys[j + 1]
            mx, my = (ax + bx) / 2, (ay + by) / 2
            area = (bx - ax) * (by - ay)
            if area > best_area and not any(_contains(b, mx, my) for b in boxes):
                best, best_area = (mx, my), area
    return best
