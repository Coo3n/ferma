"""Смены (расписание): CRUD, вкл/выкл, план дня по телефонам."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import scenarios
from ..schedule import scheduler

router = APIRouter(prefix="/api/schedules")


def _check_scenario(data: dict) -> None:
    key = (data or {}).get("scenario")
    if key and scenarios.get(key) is None:
        raise HTTPException(400, f"сценарий «{key}» не найден")


def _public(sched: dict) -> dict:
    sc = scenarios.get(sched["scenario"])
    return {**sched, "scenario_name": sc.name if sc else sched["scenario"],
            "scenario_missing": sc is None, "next_at": scheduler.next_run(sched)}


@router.get("")
def list_schedules():
    return [_public(s) for s in scheduler.all()]


@router.post("")
def create_schedule(data: dict = Body(...)):
    _check_scenario(data)
    try:
        return _public(scheduler.create(data))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/{sid}")
def get_schedule(sid: str):
    sched = scheduler.get(sid)
    if sched is None:
        raise HTTPException(404, "смена не найдена")
    return _public(sched)


@router.put("/{sid}")
def update_schedule(sid: str, data: dict = Body(...)):
    _check_scenario(data)
    try:
        return _public(scheduler.update(sid, data))
    except KeyError:
        raise HTTPException(404, "смена не найдена") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.delete("/{sid}")
def delete_schedule(sid: str):
    try:
        scheduler.delete(sid)
    except KeyError:
        raise HTTPException(404, "смена не найдена") from None
    return {"ok": True}


@router.post("/{sid}/toggle")
def toggle_schedule(sid: str, data: dict = Body(default={})):
    try:
        return _public(scheduler.toggle(sid, (data or {}).get("enabled")))
    except KeyError:
        raise HTTPException(404, "смена не найдена") from None


@router.get("/{sid}/plan")
def schedule_plan(sid: str):
    try:
        return scheduler.plan(sid)
    except KeyError:
        raise HTTPException(404, "смена не найдена") from None
