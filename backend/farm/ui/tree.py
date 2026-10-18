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
