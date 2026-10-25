"""Обучение: чтобы сорок телефонов не платили сорок раз.

После удачи нейросети берём узел дерева в найденной точке, строим селектор
(ui/selectors.py) и запоминаем его под ключом цели. resolve() подмешивает
запомненные селекторы к цели, и следующий телефон находит её слоем «selector»
без нейросети. Нет узла (игра, canvas) — запоминать нечего, остаётся только
отклонение.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
import logging
import threading
import time
from pathlib import Path

from .. import config
from ..ui import scope, selectors, tree

log = logging.getLogger("farm.vlm")
_lock = threading.RLock()
MAX_PER_KEY = 3


def key(ctx, sel, text, img, at) -> str:
    raw = json.dumps([getattr(ctx, "scenario_key", ""), sel or [], list(text or []),
                      str(img or ""), list(at) if at else []],
                     ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _read() -> dict:
    try:
        data = json.loads(Path(config.VLM_LEARNED_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def lookup(k: str) -> list:
    """Запомненные селекторы цели."""
    with _lock:
        entry = _read().get(k) or {}
    sels = entry.get("sel") if isinstance(entry, dict) else None
    return [s for s in (sels or []) if isinstance(s, dict)]


def remember(k: str, sels: list, scenario_key: str = "") -> int:
    """Записать; вернуть, сколько раз цель уже учили (с этим разом)."""
    with _lock:
        data = _read()
        entry = data.get(k) if isinstance(data.get(k), dict) else {}
        have = [s for s in entry.get("sel", []) if isinstance(s, dict)]
        for s in sels:
            if s not in have:
                have.append(s)
        entry.update(sel=have[-MAX_PER_KEY:], scenario=scenario_key, at=time.time(),
                     n=int(entry.get("n", 0)) + 1)
        data[k] = entry
        path = Path(config.VLM_LEARNED_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Поддерживается один процесс фермы: межпроцессного замка нет. Имя
        # tmp уникальное, чтобы два потока не писали в один файл.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, path)
        return entry["n"]


def selector_for_point(nodes, x: float, y: float) -> dict | None:
    """Устойчивый селектор кликабельного узла под точкой или None."""
    node = tree.node_at(nodes, x, y)
    if node is None:
        return None
    target, _ = selectors.resolve_target(nodes, node)
    sel_node = target
    if not selectors._labeled(target):
        sel_node = selectors.resolve_down(nodes, target) or target
    for c in selectors.build_selectors(nodes, sel_node):
        if (c["call"] != "click" or c["matches"] != 1 or c.get("dynamic")
                or c.get("fragile") or c.get("oversized")):
            continue
        try:
            d = scope.parse_args(c["args"])
        except scope.ScopeError:
            continue
        if d and all(k in selectors_keys() for k in d):
            return d
    return None


def selectors_keys():
    from ..context import SEL_KEY_TYPES
    return SEL_KEY_TYPES
