"""Счётчики «потолка за сутки»: сколько аккаунт успел сделать сегодня.

Ключи такие же, как их пишет ферма на прогоне: «account:<id>» и, когда
аккаунт к телефону не привязан, «phone:<serial>».
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import budget

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.get("")
def counters(day: str = ""):
    return {"day": day or budget.today(), "counters": budget.state(day=day)}


@router.post("/reset")
def reset(payload: dict = Body(...)):
    """Обнулить счётчик. Название не задано — все счётчики этого ключа."""
    key = str(payload.get("key") or "")
    if not key:
        raise HTTPException(400, "не указано, чей счётчик обнулить")
    budget.reset(key, str(payload.get("name") or ""))
    return {"ok": True}
