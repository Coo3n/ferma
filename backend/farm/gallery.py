"""Галерея готовых сюжетов: карточки и копирование в «Мои».

Метаданные читаются через ast, файл не выполняется: карточка не должна
импортировать сюжет (а с ним TikTok-селекторы и прочее) и не должна
конфликтовать по имени модуля с копией того же сюжета в «Моих».
"""
from __future__ import annotations

import ast
import json
import logging
import re
import shutil

from . import config, steps_text
from .recorder import save as saver, steps as schema

log = logging.getLogger("farm.gallery")

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_WANTED = ("NAME", "DESCRIPTION", "GALLERY", "STEPS")
RECIPE_SUFFIX = ".recipe.json"


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


def _code_steps(value) -> list:
    """STEPS кодового сюжета: список строк -> [{"text", "depth": 0}]."""
    if not isinstance(value, (list, tuple)):
        return []
    return [{"text": x, "depth": 0} for x in value if isinstance(x, str) and x.strip()]


def _code_card(path):
    meta = _meta(path)
    if not meta or "NAME" not in meta:
        return None
    tag = meta.get("GALLERY") if isinstance(meta.get("GALLERY"), dict) else {}
    return {
        "key": path.stem,
        "name": str(meta["NAME"]),
        "description": str(meta.get("DESCRIPTION") or meta["_doc"]),
        "platform": str(tag.get("platform", "")),
        "verified": bool(tag.get("verified", False)),
        "package": str(tag.get("package", "")),
        "added": _added(path.stem),
        "kind": "code",
        "editable": False,
        "steps_text": _code_steps(meta.get("STEPS")),
        "params": [],
    }


def _recipe_key(path) -> str:
    return path.name[:-len(RECIPE_SUFFIX)]


def _load_recipe(path):
    """(meta, params, steps, gallery-тег) из файла рецепта; None, если негодный."""
    key = _recipe_key(path)
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise schema.StepError("рецепт должен быть объектом")
        meta = schema.normalize_meta(data.get("meta"))
        params = schema.normalize_params(data.get("params"))
        steps = schema.normalize_steps(data.get("steps"))
        schema.check_params(params, steps)
        if not steps:
            raise schema.StepError("нет ни одного шага")
    except (OSError, ValueError, schema.StepError) as e:  # JSONDecodeError - ValueError
        log.warning("галерея: рецепт %s пропущен: %s", key, e)
        return None
    tag = data.get("gallery") if isinstance(data.get("gallery"), dict) else {}
    return meta, params, steps, tag


def _recipe_card(path):
    key = _recipe_key(path)
    if not KEY_RE.match(key):
        return None
    loaded = _load_recipe(path)
    if loaded is None:
        return None
    meta, params, steps, tag = loaded
    return {
        "key": key,
        "name": str(meta.get("name") or key),
        "description": str(meta.get("description") or ""),
        "platform": str(tag.get("platform", "")),
        "verified": bool(tag.get("verified", False)),
        "package": str(tag.get("package", "")),
        "added": _added(key),
        "kind": "recipe",
        "editable": True,
        "steps_text": steps_text.describe(steps),
        "params": [{"name": n, "label": str(spec.get("label") or n)} for n, spec in params.items()],
    }


def items() -> list:
    out = []
    for path in sorted(config.GALLERY_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        card = _code_card(path)
        if card:
            out.append(card)
    for path in sorted(config.GALLERY_DIR.glob(f"*{RECIPE_SUFFIX}")):
        if path.name.startswith("_"):
            continue
        card = _recipe_card(path)
        if card:
            out.append(card)
    out.sort(key=lambda c: c["key"])
    return out


def _add_recipe(key: str, path) -> str:
    loaded = _load_recipe(path)
    if loaded is None:
        raise KeyError(key)
    meta, params, steps, _ = loaded
    target = key
    n = 1
    while True:
        try:
            saver.save(target, meta, params, steps, overwrite=False)
            return target
        except saver.Conflict:
            n += 1
            target = f"{key}_{n}"


def add(key: str) -> str:
    """Скопировать сюжет в «Мои». Возвращает ключ копии (key, key_2, …)."""
    if not KEY_RE.match(key or ""):
        raise KeyError(key)
    recipe = config.GALLERY_DIR / f"{key}{RECIPE_SUFFIX}"
    if recipe.is_file():
        return _add_recipe(key, recipe)
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
