"""Конструктор сценариев: предпросмотр кода и сохранение файла."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import PlainTextResponse

from .. import adb, scenarios
from ..recorder import codegen, presets, save as saver, steps as schema, validate as recorder_validate

router = APIRouter(prefix="/api/recorder")


@router.get("/presets")
def preset_list():
    """Библиотека готовых скриптов — конструктор показывает её списком."""
    return presets.PRESETS


@router.get("/schema")
def recipe_schema():
    """Какие шаги и поля понимает конструктор — для ИИ-помощника (docs/recipe-format.md)."""
    return schema.schema()


@router.get("/recipe/{key}")
def recipe(key: str):
    """Шаги записанного сценария — чтобы открыть его в конструкторе на правку.

    Отдаём то, что конструктор когда-то прислал, плюс кропы в base64: правка
    сохраняется тем же /save, и картинки должны уехать назад целыми, иначе
    слой поиска по шаблону отвалится после первой же правки.
    """
    data = saver.load_recipe(key)
    # Рецепт-сирота при рукописном (или пропавшем) .py: открыть его на правку
    # значило бы затем заменить чужой файл кодом, собранным из старого рецепта.
    try:
        py = saver.target_path(key)
    except saver.SaveError:
        py = None
    if data is not None and (py is None or not py.is_file() or not scenarios.is_recorded(py)):
        raise HTTPException(404, "рецепт найден, но файла сценария нет либо он "
                                 "написан вручную — открыть на правку нельзя")
    if data is None:
        raise HTTPException(404, "сценарий нельзя открыть на правку: "
                                 "он не записан конструктором")
    data["key"] = key
    data["assets"] = saver.load_assets(key)
    return data


def _io_detail(err) -> str:
    """Текст 500 при сбое диска; «файлы не изменены» — только если откат удался."""
    tail = ("Файлы возвращены в прежнее состояние, ничего не изменилось."
            if err.rolled_back else
            "Откат удался не полностью: сохраните ещё раз, чтобы выровнять файлы.")
    return f"{err} {tail}"


def _parse(payload: dict):
    """Разбор общего тела обоих запросов: meta, params и шаги."""
    try:
        meta = schema.normalize_meta(payload.get("meta"))
        params = schema.normalize_params(payload.get("params"))
        items = schema.normalize_steps(payload.get("steps"))
        schema.check_params(params, items)
    except schema.StepError as e:
        raise HTTPException(400, str(e))
    return meta, params, items


@router.post("/preview", response_class=PlainTextResponse)
def preview(payload: dict = Body(...)):
    meta, params, items = _parse(payload)
    return codegen.render(meta, params, items)


@router.post("/validate")
def validate(payload: dict = Body(...)):
    """Проверка сценария до запуска: ошибки и предупреждения по шагам.

    Необязательный `serial` включает проверку установленных пакетов; сбой
    опроса устройства не считается ошибкой сценария — проверка просто пропущена.
    """
    blocks = {sc.key: not sc.error for sc in scenarios.discover()}
    packages = None
    serial = payload.get("serial")
    if serial:
        try:
            packages = set(adb.list_packages(serial, third_party_only=False))
        except Exception:  # noqa: BLE001 — устройство не обязано отвечать
            packages = None
    assets = set(payload["assets"]) if isinstance(payload.get("assets"), dict) else None
    return recorder_validate.validate(payload, blocks, packages, assets)


@router.post("/save")
def save_scenario(payload: dict = Body(...)):
    meta, params, items = _parse(payload)
    try:
        path = saver.save(payload.get("key"), meta, params, items,
                          bool(payload.get("overwrite")),
                          assets=payload.get("assets"),
                          screen_width=payload.get("screen_width"))
    except saver.Conflict as e:
        raise HTTPException(409, str(e))
    except saver.SaveIOError as e:
        raise HTTPException(500, _io_detail(e))
    except saver.SaveError as e:
        raise HTTPException(400, str(e))
    return {"key": payload.get("key"), "path": str(path)}
