"""Устройства: карточки, настройки, диагностика, инспектор."""
from __future__ import annotations

import base64
import shutil
import subprocess
import time

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import adb, config, control, streaming
from .. import ui as uitree
from ..devices import net, registry

router = APIRouter(prefix="/api/devices")
tags_router = APIRouter(prefix="/api/tags")

SCRCPY_MAX_SIZE = "900"


def _require_device(serial: str):
    device = registry.get(serial)
    if device is None:
        raise HTTPException(404, "устройство не найдено")
    return device


@router.get("")
def list_devices():
    return [d.to_dict() for d in registry.all()]


@router.get("/{serial}")
def get_device(serial: str):
    device = _require_device(serial)
    data = device.to_dict()
    if device.online:
        try:
            data["current_app"] = control.current_app(serial)
        except Exception as e:  # noqa: BLE001
            data["current_app"] = f"—  ({e})"
    return data


@router.post("/{serial}/label")
def set_label(serial: str, label: str = Body(..., embed=True)):
    registry.set_label(serial, label.strip())
    return {"ok": True}


@router.post("/{serial}/group")
def set_group(serial: str, group: str = Body("", embed=True)):
    registry.set_group(serial, group)
    return {"ok": True}


@router.post("/{serial}/tags")
def set_tags(serial: str, tags: list[str] = Body(..., embed=True)):
    return {"ok": True, "tags": registry.set_tags(serial, tags)}


@tags_router.get("")
def all_tags():
    return registry.all_tags()


@router.post("/{serial}/enabled")
def set_enabled(serial: str, enabled: bool = Body(..., embed=True)):
    registry.set_enabled(serial, enabled)
    return {"ok": True}


@router.post("/{serial}/recover")
def recover(serial: str):
    control.forget_size(serial)
    streaming.drop(serial)
    return {"ok": True, "message": registry.recover(serial)}


@router.post("/{serial}/prepare")
def prepare(serial: str):
    """Применить настройки фермы. Уже настроенное устройство не трогаем."""
    pending = control.pending_settings(serial)
    if not pending:
        return {"ok": True, "already": True, "applied": []}
    return {"ok": True, "already": False, "applied": control.prepare_for_farm(serial)}


@router.post("/{serial}/tcpip")
def switch_to_tcpip(serial: str, port: int = Body(config.NETWORK_PORT, embed=True)):
    """Перевести устройство с провода на TCP и поставить адрес под сторожа.

    После этого USB можно отсоединить: подключение держит сторож.
    """
    device = _require_device(serial)
    if adb.is_network_serial(serial):
        raise HTTPException(400, "устройство уже подключено по сети")
    if not device.online:
        raise HTTPException(400, "устройство не в сети — переключать нечего")

    ip = adb.device_ip(serial)
    if not ip:
        raise HTTPException(400, "не удалось определить IP устройства — проверьте, что оно в той же сети")
    try:
        adb.tcpip(serial, port)
    except adb.AdbError as e:
        raise HTTPException(500, f"tcpip не сработал: {e}")

    time.sleep(1.5)  # adbd на устройстве перезапускается
    address = f"{ip}:{port}"
    target = net.add(address, label=device.label or device.model)
    ok, message = net.connect_now(address)
    registry.refresh_once()
    net.settle()
    return {
        "ok": ok,
        "address": address,
        "message": f"{address}: {message}" if ok else f"{address}: не подключиться — {message}",
        "target": target.to_dict(),
    }


@router.get("/{serial}/packages")
def packages(serial: str, all: bool = Query(False)):
    return adb.list_packages(serial, third_party_only=not all)


@router.get("/{serial}/hierarchy", response_class=PlainTextResponse)
def hierarchy(serial: str):
    try:
        return control.dump_hierarchy(serial)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@router.get("/{serial}/inspect")
def inspect_screen(serial: str):
    """Снимок экрана и разобранная иерархия одним ответом.

    Атомарность обязательна: раздельные запросы разъезжаются во времени, и
    рамки лягут мимо элементов.
    """
    try:
        xml = control.dump_hierarchy(serial)
        shot = control.screenshot(serial, max_width=config.ARTIFACT_MAX_WIDTH, quality=85)
        width, height = control.size(serial)
        nodes = uitree.parse(xml, width, height)
    except uitree.InspectError as e:
        raise HTTPException(500, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"не удалось снять экран: {e}")
    return {
        "width": width,
        "height": height,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii"),
        "nodes": uitree.to_payload(nodes),
    }


@router.get("/{serial}/logcat", response_class=PlainTextResponse)
def logcat(serial: str, lines: int = 300):
    return control.logcat_tail(serial, lines)


@router.post("/{serial}/scrcpy")
def open_scrcpy(serial: str):
    executable = shutil.which("scrcpy")
    if not executable:
        raise HTTPException(400, "scrcpy не установлен: brew install scrcpy")
    device = registry.get(serial)
    title = device.name if device else serial
    subprocess.Popen(
        [executable, "-s", serial, "--window-title", title,
         "--stay-awake", "--no-audio", "--max-size", SCRCPY_MAX_SIZE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "message": f"scrcpy запущен для {title}"}
