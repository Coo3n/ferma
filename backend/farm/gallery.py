"""Галерея готовых сюжетов: карточки и копирование в «Мои».

Метаданные читаются через ast, файл не выполняется: карточка не должна
импортировать сюжет (а с ним TikTok-селекторы и прочее) и не должна
конфликтовать по имени модуля с копией того же сюжета в «Моих».
"""
from __future__ import annotations

import ast
import logging
import re
import shutil

from . import config

log = logging.getLogger("farm.gallery")

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_WANTED = ("NAME", "DESCRIPTION", "GALLERY")


def _meta(path):
    """NAME/DESCRIPTION/GALLERY из исходника или None, если файл негодный."""
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError) as e:
        log.warning("галерея: %s не читается: %s", path.name, e)
        return None
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in _WANTED):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    doc = ast.get_docstring(tree) or ""
    found["_doc"] = doc.strip().splitlines()[0] if doc.strip() else ""
    return found


def _added(key: str) -> bool:
    """Есть ли в «Моих» копия: сам ключ или ключ_N."""
    pattern = re.compile(rf"^{re.escape(key)}(_\d+)?$")
    return any(pattern.match(p.stem) for p in config.SCENARIOS_DIR.glob("*.py"))


def items() -> list:
    out = []
    for path in sorted(config.GALLERY_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        meta = _meta(path)
        if not meta or "NAME" not in meta:
            continue
        tag = meta.get("GALLERY") if isinstance(meta.get("GALLERY"), dict) else {}
        out.append({
            "key": path.stem,
            "name": str(meta["NAME"]),
            "description": str(meta.get("DESCRIPTION") or meta["_doc"]),
            "platform": str(tag.get("platform", "")),
            "verified": bool(tag.get("verified", False)),
            "package": str(tag.get("package", "")),
            "added": _added(path.stem),
        })
    return out


def add(key: str) -> str:
    """Скопировать сюжет в «Мои». Возвращает ключ копии (key, key_2, …)."""
    if not KEY_RE.match(key or ""):
        raise KeyError(key)
    src = config.GALLERY_DIR / f"{key}.py"
    if not src.is_file():
        raise KeyError(key)
    target = key
    n = 1
    while (config.SCENARIOS_DIR / f"{target}.py").exists():
        n += 1
        target = f"{key}_{n}"
    shutil.copyfile(src, config.SCENARIOS_DIR / f"{target}.py")
    return target
