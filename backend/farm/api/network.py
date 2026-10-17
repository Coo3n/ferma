"""Сетевые устройства: список адресов плат, подключение, сторож."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import config, streaming
from ..devices import net, registry

router = APIRouter(prefix="/api/network")


def _require_target(address: str):
    target = net.get(address)
    if target is None:
        raise HTTPException(404, "адрес не в списке")
    return target


@router.get("")
def list_targets():
    return {
        "port": config.NETWORK_PORT,
        "tick": config.NETWORK_TICK,
        "targets": [t.to_dict() for t in net.all()],
    }


@router.post("")
def add_target(address: str = Body(..., embed=True), label: str = Body("", embed=True)):
    """Добавить плату и сразу попытаться подключиться."""
    try:
        target = net.add(address, label)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if label.strip():
        # Метка живёт в devices.json — там же, где имена телефонов, чтобы
        # плитка фермы не знала о двух источниках названий.
        registry.set_label(target.address, label.strip())
    ok, message = net.connect_now(target.address)
    registry.refresh_once()
    net.settle()
    return {"ok": True, "connected": ok, "message": message, "target": target.to_dict()}


@router.delete("/{address}")
def remove_target(address: str):
    _require_target(address)
    net.remove(address)
    streaming.drop(address)
    registry.forget(address)
    return {"ok": True, "message": f"{address} убран из списка"}


@router.post("/{address}/connect")
def connect_target(address: str):
    _require_target(address)
    ok, message = net.connect_now(address)
    registry.refresh_once()
    net.settle()
    return {"ok": ok, "message": message, "target": net.get(address).to_dict()}


@router.post("/{address}/enabled")
def set_target_enabled(address: str, enabled: bool = Body(..., embed=True)):
    _require_target(address)
    target = net.set_enabled(address, enabled)
    return {"ok": True, "target": target.to_dict()}
