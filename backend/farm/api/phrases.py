"""Группы быстрых фраз для панели «Ввести текст»."""
from __future__ import annotations

import time

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

from .. import phrase_store

router = APIRouter(prefix="/api/phrases")


@router.get("")
def get_phrases():
    return phrase_store.load()


@router.put("")
def put_phrases(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(400, "ожидается объект с группами")
    return phrase_store.save(payload)


@router.post("/import")
def import_phrases(payload: dict = Body(...)):
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise HTTPException(400, "нужен текст файла")
    group = payload.get("group")
    name = payload.get("filename")
    is_csv = isinstance(name, str) and name.lower().endswith(".csv")
    before = phrase_store.load()
    try:
        after = phrase_store.import_text(before, group, payload["text"], csv=is_csv)
    except ValueError as e:
        raise HTTPException(404, str(e))
    saved = phrase_store.save(after)
    count = lambda d: sum(len(g["items"]) for g in d["groups"])  # noqa: E731
    return {**saved, "added": count(saved) - count(before)}


@router.get("/export")
def export_phrases(group: str = Query("")):
    try:
        blob = phrase_store.export_csv(phrase_store.load(), group or None)
    except ValueError as e:
        raise HTTPException(404, str(e))
    name = time.strftime("phrases-%Y%m%d.csv")
    return Response(blob, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
