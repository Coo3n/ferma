"""Библиотека APK: приложения, которые сценарий ставит сам (шаг ensure_app)."""
from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Body, HTTPException, Query, Request

from .. import apkinfo, apklib
from . import bulk

router = APIRouter(prefix="/api/apks")

_BUNDLES = (".apks", ".xapk", ".apkm")


@router.get("")
def list_apks():
    used = apklib.usage()
    return [{**a, "used": used.get(a["package"], 0)} for a in apklib.list_all()]


@router.post("")
async def upload(request: Request, name: str = Query("app.apk")):
    """Тело запроса — сам APK. Тот же пакет заменяет прежний файл."""
    if name.lower().endswith(_BUNDLES):
        raise HTTPException(400, "наборы .apks/.xapk пока не поддерживаются — нужен один файл .apk")
    tmp = await bulk._upload(request, name)
    try:
        return await run_in_threadpool(apklib.add, tmp)
    except apkinfo.ApkError as e:
        raise HTTPException(400, str(e))
    finally:
        bulk._discard(tmp)


@router.patch("/{package}")
def rename_apk(package: str, payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "впишите название")
    out = apklib.rename(package, name)
    if out is None:
        raise HTTPException(404, "такого приложения нет в библиотеке")
    return out


@router.delete("/{package}")
def delete_apk(package: str):
    if not apklib.remove(package):
        raise HTTPException(404, "такого приложения нет в библиотеке")
    return {"ok": True}
