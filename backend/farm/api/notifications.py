"""Монитор уведомлений: список отслеживаемых приложений и срез по телефонам."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Body, Query

from .. import notifications
from ..devices import registry

router = APIRouter(prefix="/api/notifications")
WORKERS = 12


@router.get("/watch")
def get_watch():
    return {"packages": notifications.watched()}


@router.put("/watch")
def put_watch(payload: dict = Body(...)):
    return {"packages": notifications.set_watched(payload.get("packages"))}


@router.get("")
def scan(packages: str = Query(""), text: int = Query(0)):
    """Срез по всем телефонам в сети: {serial: {name, count, items | error}}."""
    wanted = [p.strip() for p in packages.split(",") if p.strip()] or notifications.watched()
    phones = [d for d in registry.all() if d.online]

    def one(d):
        try:
            return d.serial, {"name": d.name, **notifications.scan_phone(d.serial, wanted, bool(text))}
        except Exception as e:  # noqa: BLE001 — один телефон не должен ронять срез
            return d.serial, {"name": d.name, "count": 0, "items": [], "error": str(e)[:200]}

    if not phones:
        return {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(phones))) as pool:
        return dict(pool.map(one, phones))
