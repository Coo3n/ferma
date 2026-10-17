"""Чтение UI устройства: дерево узлов и подбор селекторов."""
from .selectors import build_selectors, resolve_target, to_payload
from .tree import InspectError, Node, node_at, parse, parse_bounds

__all__ = [
    "InspectError", "Node", "parse", "parse_bounds", "node_at",
    "resolve_target", "build_selectors", "to_payload",
]
