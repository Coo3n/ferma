"""Общее состояние фермы: статус, перезапуск adb."""
from __future__ import annotations

import shutil
import time

from fastapi import APIRouter

from .. import adb, config
from ..deviations import deviations
from ..devices import net, pool, registry
from ..devices.runner import runner

router = APIRouter()

@router.get("/api/status")
def status():
    devices = registry.all()
    targets = net.all()
    return {
        "adb": registry.adb_version,
        "adb_path": adb.ADB,
        "devices_total": len(devices),
        "devices_online": sum(1 for d in devices if d.online),
        "network_total": len(targets),
        "network_online": sum(1 for t in targets if t.state == "connected"),
        "jobs": runner.stats(),
        # Непрочитанные отклонения от сценариев едут вместе с остальным
        # состоянием: значок в навигации не стоит отдельного опроса каждые
        # три секунды.
        "deviations_unseen": deviations.unseen(),
        "scrcpy": bool(shutil.which("scrcpy")),
        "time": time.time(),
    }


@router.post("/api/adb/restart")
def restart_adb():
    adb.kill_server()
    adb.start_server()
    pool.drop_all()
    # Перезапуск сервера рвёт все TCP-подключения разом: сетевые платы после
    # него надо поднимать заново, иначе ферма полчаса ждёт откатов сторожа.
    reconnected = net.tick({})
    registry.refresh_once()
    net.settle()
    message = "телефоны переподключены"
    if reconnected:
        message += f", по Wi-Fi: {len(reconnected)}"
    return {"ok": True, "message": message}
