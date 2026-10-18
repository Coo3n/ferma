"""Сценарии: список, исходник, запуск."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import guards, obstacle, scenarios
from ..devices.runner import runner
from ..recorder import save as saver
from .detours import scan_obstacles

router = APIRouter()

# Метка запуска приходит из браузера только у пробного запуска: остальные
# телефоны добавляются в тот же запуск, что и пробный, — одна строка в
# «Запусках», а не две. Формат — как у runner.submit (uuid hex).
_BATCH_RE = re.compile(r"[0-9a-f]{6,32}")


def _batch_of(payload: dict) -> str | None:
    batch = payload.get("batch")
    if batch in (None, ""):
        return None
    if not isinstance(batch, str) or not _BATCH_RE.fullmatch(batch):
        raise HTTPException(400, "неверная метка запуска")
    return batch


def _structure(key: str) -> tuple[int | None, int | None]:
    """Число шагов и развилок в рецепте — только у сценариев из конструктора."""
    рецепт = saver.load_recipe(key)
    if not рецепт:
        return None, None
    шаги = рецепт.get("steps") or []
    ветки = sum(1 for шаг in шаги if шаг.get("kind") == "branch")
    # Заголовок повтора — рамка вокруг шагов, а не шаг: в счёт не идёт.
    return sum(1 for шаг in шаги if шаг.get("kind") != "loop"), ветки


def _package_of(params: dict) -> str:
    """Пакет из параметра `package`, если сценарий его объявляет.

    Параметр хранится либо как голое значение, либо как словарь со `default`
    — тем же способом, что разбирает paramField() на фронте.
    """
    raw = (params or {}).get("package")
    if isinstance(raw, dict):
        return str(raw.get("default") or "")
    return str(raw or "")


def _uncovered(package: str, scan_cache: dict) -> int | None:
    """Непокрытые преграды по пакету приложения — не по сценарию: пакет мог
    получить преграду через любой из бьющих в него сценариев.

    `scan_cache` живёт ровно один вызов list_scenarios(): несколько сценариев
    часто делят один package, и без кэша каждый заново обходит весь
    ARTIFACTS_DIR — на список, который фронт опрашивает раз в 15с, это лишний
    проход по диску на каждый повтор пакета."""
    if not package:
        return None
    if package not in scan_cache:
        scan_cache[package] = scan_obstacles(package)
    rules = [{"when": {"any": g.when}} for g in guards.load(package)]
    return len(obstacle.uncovered(scan_cache[package], rules))


@router.get("/api/scenarios")
def list_scenarios(reload: bool = Query(False)):
    out = []
    scan_cache: dict = {}
    for s in scenarios.discover(force=reload):
        item = s.to_dict()
        # Правка открывается только по рецепту: .py обратно в шаги не
        # разбирается. У сценариев, записанных до появления рецептов, кнопки
        # правки не будет — врать про неё хуже, чем не показывать.
        item["editable"] = bool(s.recorded and saver.has_recipe(s.key))
        item["steps"], item["branches"] = (
            _structure(s.key) if item["editable"] else (None, None))
        stats = runner.scenario_stats(s.key)
        item["passed"], item["failed"] = stats["passed"], stats["failed"]
        item["uncovered"] = _uncovered(_package_of(s.params), scan_cache)
        out.append(item)
    return out


@router.get("/api/scenarios/{key}/source", response_class=PlainTextResponse)
def scenario_source(key: str):
    scenario = scenarios.get(key)
    if scenario is None:
        raise HTTPException(404, "сценарий не найден")
    return Path(scenario.path).read_text("utf-8")


@router.post("/api/run")
def run_scenario(payload: dict = Body(...)):
    key = payload.get("scenario")
    serials = payload.get("serials") or []
    if not key:
        raise HTTPException(400, "не указан сценарий")
    if not serials:
        raise HTTPException(400, "не выбрано ни одного устройства")
    batch = _batch_of(payload)
    try:
        jobs = runner.submit(key, serials, payload.get("params"),
                             int(payload.get("repeat", 1)),
                             start_step=int(payload.get("start_step") or 0),
                             stop_step=(int(payload["stop_step"])
                                        if payload.get("stop_step") is not None else None),
                             speed=float(payload.get("speed") or 1.0),
                             batch=batch)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "jobs": [j.to_dict() for j in jobs],
            "batch": jobs[0].batch if jobs else ""}


@router.post("/api/run/preflight")
def run_preflight(scenario: str = Body(...), serials: list[str] = Body(...)):
    """Кто из телефонов готов к запуску — показывается в окне запуска до нажатия."""
    sc = scenarios.get(scenario)
    if sc is None:
        raise HTTPException(404, "сценарий не найден")
    return scenarios.preflight(sc, serials)


@router.delete("/api/scenarios/{key}")
def delete_scenario(key: str):
    """Удалять можно только записанное конструктором — чужой код не трогаем."""
    scenario = scenarios.get(key)
    if scenario is None:
        raise HTTPException(404, "сценарий не найден")
    if not scenario.recorded:
        raise HTTPException(403, "удалять можно только сценарии из конструктора")
    saver.delete(key, Path(scenario.path))   # .py и ассеты под одним замком
    scenarios.discover(force=True)
    return {"ok": True}
