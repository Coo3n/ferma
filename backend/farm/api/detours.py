"""Обучение на месте: показанный человеком выход становится отводом.

Сценарий упал на незнакомом экране — человек открывает устройство, показывает
кликами, как выбраться, и сохраняет. Отсюда рождаются две вещи разом:
обычный сценарий-блок в scenarios/ и страж в guards/<пакет>.json, который
зовёт этот блок, когда преграда встретится снова.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from .. import config, guards, obstacle
from ..recorder import save as saver, steps as schema
from .recorder import _io_detail

router = APIRouter(prefix="/api/detours")

# Пакет идёт в имя файла — пускаем только то, чем пакет Android и бывает.
PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)*$")

# Журнал хранит сотни задач; карта смотрит только свежие — чинить стоит то,
# обо что спотыкаются сейчас, а не год назад.
MAP_SCAN_JOBS = 60


def _rules_path(package: str) -> Path:
    root = Path(config.GUARDS_DIR)
    if not package:
        return root / "global.json"
    if not PACKAGE_RE.match(package):
        raise HTTPException(400, f"недопустимый пакет «{package}»")
    path = (root / f"{package}.json").resolve()
    if not path.is_relative_to(root.resolve()):
        raise HTTPException(400, "путь вне папки стражей")
    return path


@router.post("")
def create_detour(payload: dict = Body(...)):
    """Записанные шаги + условие → блок в scenarios/ и страж в guards/."""
    key = payload.get("key")
    when = payload.get("when")
    if not isinstance(when, dict) or not when:
        raise HTTPException(400, "не выбрано условие: по чему узнавать преграду")

    try:
        meta = schema.normalize_meta({
            "name": payload.get("name") or key,
            "description": "Отвод: записан обучением на месте",
            # Отвод работает внутри чужого прогона: свои watchers и человечный
            # режим он включать не должен, они уже настроены вызывающим.
            "watch_popups": False,
            "human": False,
        })
        items = schema.normalize_steps(payload.get("steps"))
        params = schema.normalize_params(payload.get("params"))
        schema.check_params(params, items)
    except schema.StepError as e:
        raise HTTPException(400, str(e))

    path = _rules_path(payload.get("package") or "")
    try:
        saver.save(key, meta, params, items,
                   assets=payload.get("assets"),
                   screen_width=payload.get("screen_width"))
    except saver.Conflict as e:
        raise HTTPException(409, str(e))
    except saver.SaveIOError as e:
        raise HTTPException(500, _io_detail(e))
    except saver.SaveError as e:
        raise HTTPException(400, str(e))

    # Правило дописывается к существующим: в одном приложении преград много.
    правила = []
    if path.exists():
        try:
            правила = json.loads(path.read_text("utf-8")) or []
        except (OSError, json.JSONDecodeError):
            правила = []
    правила.append({
        "name": key,
        "when": {"any": [when]},
        "action": {"run": key},
        "max_fires": int(payload.get("max_fires") or 2),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(правила, ensure_ascii=False, indent=1), "utf-8")
    guards._cache.pop(str(path), None)   # горячая перезагрузка ждёт смены mtime

    return {"key": key, "rules": str(path)}


def _read_rules(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _write_rules(path: Path, rules: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=1), "utf-8")
    guards._cache.pop(str(path), None)   # горячая перезагрузка ждёт смены mtime


@router.post("/rules")
def add_rule(payload: dict = Body(...)):
    """Правило «окно → что сделать» без обучения записью: «если видно
    «Не сейчас» — нажать её», «— клавиша Назад», «— запустить команду».

    package пустой — для всех приложений (global.json)."""
    package = payload.get("package") or ""
    path = _rules_path(package)
    rules = _read_rules(path)
    base = str(payload.get("name") or "окно").strip()[:60] or "окно"
    names = {r.get("name") for r in rules if isinstance(r, dict)}
    name, n = base, 2
    while name in names:
        name, n = f"{base} ({n})", n + 1
    raw = {"name": name, "when": {"any": payload.get("when") or []},
           "action": payload.get("action") or {},
           "max_fires": int(payload.get("max_fires") or guards.DEFAULT_MAX_FIRES)}
    # Маленькая картинка окна для списка правил — человеку легче узнать окно
    # по виду, чем по «элемент post header…». Стражи её не читают.
    img = payload.get("img")
    if isinstance(img, str) and img.startswith("data:image/") and len(img) < 60_000:
        raw["img"] = img
    try:
        guards._parse_guard(raw, path.stem)
    except guards.GuardError as e:
        raise HTTPException(400, str(e))
    run = raw["action"].get("run")
    if run and not re.match(r"^[a-z][a-z0-9_]{0,47}$", run):
        raise HTTPException(400, f"неизвестный сценарий «{run}»")
    rules.append(raw)
    _write_rules(path, rules)
    return {"ok": True, "name": name, "source": path.stem}


@router.delete("/rules")
def delete_rule(name: str, package: str = ""):
    path = _rules_path(package)
    rules = _read_rules(path)
    left = [r for r in rules if not (isinstance(r, dict) and r.get("name") == name)]
    if len(left) == len(rules):
        raise HTTPException(404, f"правила «{name}» нет")
    _write_rules(path, left)
    return {"ok": True}


@router.get("/scenario/{key}")
def scenario_rules(key: str):
    """Какие правила окон действуют на сценарий: по приложениям из его шагов
    (запуск, закрытие, «приложение готово») плюс общие для всех."""
    рецепт = saver.load_recipe(key) or {}
    пакеты = []
    for шаг in рецепт.get("steps") or []:
        pkg = ((шаг or {}).get("args") or {}).get("package") if isinstance(шаг, dict) else None
        if isinstance(pkg, str) and PACKAGE_RE.match(pkg) and pkg not in пакеты:
            пакеты.append(pkg)
    seen, rules = set(), []
    for pkg in пакеты or [""]:
        for g in guards.load(pkg):
            if (g.source, g.name) in seen:
                continue
            seen.add((g.source, g.name))
            rules.append({"name": g.name, "when": {"any": g.when}, "action": g.action,
                          "source": g.source, "img": _rule_img(g)})
    return {"off": key in guards.scenarios_off(), "packages": пакеты, "rules": rules}


@router.post("/scenario/{key}")
def scenario_rules_toggle(key: str, payload: dict = Body(...)):
    if not re.match(r"^[a-z][a-z0-9_]{0,47}$", key):
        raise HTTPException(400, "неверный ключ сценария")
    guards.set_scenario_off(key, bool(payload.get("off")))
    return {"ok": True, "off": key in guards.scenarios_off()}


@router.put("/rules")
def edit_rule(payload: dict = Body(...)):
    """Изменить правило: действие и/или где действует (перенос между файлами)."""
    name = payload.get("name") or ""
    src = _rules_path(payload.get("package") or "")
    rules = _read_rules(src)
    found = next((r for r in rules if isinstance(r, dict) and r.get("name") == name), None)
    if found is None:
        raise HTTPException(404, f"правила «{name}» нет")
    new = dict(found)
    if "action" in payload:
        new["action"] = payload["action"]
    try:
        guards._parse_guard(new, src.stem)
    except guards.GuardError as e:
        raise HTTPException(400, str(e))
    target_pkg = payload.get("to_package", payload.get("package") or "")
    dst = _rules_path(target_pkg)
    if dst == src:
        _write_rules(src, [new if r is found else r for r in rules])
    else:
        _write_rules(src, [r for r in rules if r is not found])
        dst_rules = _read_rules(dst)
        names = {r.get("name") for r in dst_rules if isinstance(r, dict)}
        base, n = new["name"], 2
        while new["name"] in names:
            new["name"], n = f"{base} ({n})", n + 1
        _write_rules(dst, dst_rules + [new])
    return {"ok": True, "name": new["name"]}


def scan_obstacles(package: str = "") -> list:
    """Слепки преград из артефактов последних задач, свежие первыми.

    Слепков в задаче несколько: obstacle.json от падения и
    obstacle_escaped_NN.json на каждый экран, обойдённый вслепую. Вторые не
    менее ценны: прогон доехал, но чем был тот экран, ферма не знает, и
    вслепую обходит его каждый раз заново.

    Вынесено из detour_map(): список сценариев тоже считает непокрытые
    преграды по пакету (для бейджа здоровья), и второй копии этого сканирования
    заводить незачем.
    """
    слепки = []
    корень = Path(config.ARTIFACTS_DIR)
    if not корень.is_dir():
        return слепки
    # свежие задачи первыми: старые падения чинить уже поздно
    папки = sorted(корень.iterdir(), key=lambda p: p.stat().st_mtime
                   if p.exists() else 0, reverse=True)
    for папка in папки[:MAP_SCAN_JOBS]:
        if not папка.is_dir():
            continue
        for файл in sorted(папка.glob("obstacle*.json")):
            try:
                слепок = json.loads(файл.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(слепок, dict):
                continue
            if package and слепок.get("package") != package:
                continue
            слепок["job"] = папка.name
            слепок["file"] = файл.name
            слепки.append(слепок)
    return слепки


def _rule_img(g) -> str:
    """Картинка правила из файла стражей (Guard её не хранит)."""
    path = _rules_path("" if g.source == "global" else g.source)
    for r in _read_rules(path):
        if isinstance(r, dict) and r.get("name") == g.name:
            return r.get("img") or ""
    return ""


@router.get("")
def detour_map(package: str = ""):
    """Карта отводов: что уже умеем обходить и обо что ещё спотыкаемся.

    Непокрытые преграды собираются из артефактов упавших задач. Они и есть
    смысл этой карты: ферма встречала их в бою, но обходить не научена.
    """
    rules = [
        # when отдаём в том же виде, в каком он лежит в файле стражей:
        # Guard.when — это уже развёрнутый список, и разные формы одного поля
        # в API и на диске путали бы и фронт, и расчёт непокрытых преград.
        {"name": g.name, "when": {"any": g.when},
         "action": g.action, "source": g.source, "img": _rule_img(g)}
        for g in guards.load(package)
    ]
    return {"rules": rules, "obstacles": obstacle.uncovered(scan_obstacles(package), rules)}
