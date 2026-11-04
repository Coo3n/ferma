"""Резервная копия фермы: выгрузка, просмотр и восстановление архива."""
from __future__ import annotations

import time

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response

from .. import backup

router = APIRouter(prefix="/api/backup")


async def _read(request: Request) -> bytes:
    """Тело запроса целиком, но не больше предела: архив из чужого источника."""
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > backup.MAX_TOTAL:
            raise HTTPException(413, "файл слишком большой")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/export")
def export_backup(payload: dict = Body(default=None)):
    # POST, а не GET: в архиве может лежать приватный ключ adb, а меняющие
    # запросы сервер принимает только со своей страницы (security.py).
    try:
        blob = backup.build(bool((payload or {}).get("adb_key")))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    name = time.strftime("farm-backup-%Y%m%d-%H%M.zip")
    return Response(blob, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/inspect")
async def inspect_backup(request: Request):
    try:
        return backup.inspect(await _read(request))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/restore")
async def restore_backup(request: Request, adb_key: int = Query(0), scenarios: int = Query(0)):
    try:
        return backup.restore(await _read(request), adb_key=bool(adb_key),
                              scenarios=bool(scenarios))
    except ValueError as e:
        raise HTTPException(400, str(e))
