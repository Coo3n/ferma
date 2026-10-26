"""Галерея готовых сюжетов: список карточек и «Добавить в мои»."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import gallery
from ..recorder import save as saver

router = APIRouter()


@router.get("/api/gallery")
def list_gallery():
    return gallery.items()


@router.post("/api/gallery/{key}/add")
def add_to_mine(key: str):
    try:
        return {"key": gallery.add(key)}
    except KeyError:
        raise HTTPException(404, "такого сюжета в галерее нет")
    except saver.SaveIOError:
        raise HTTPException(500, "не удалось записать сюжет на диск")
    except saver.SaveError as e:
        raise HTTPException(400, str(e))
