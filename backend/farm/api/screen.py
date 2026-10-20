"""Трансляция экрана и ручное управление устройством.

Координаты во всех действиях нормализованные (0..1), чтобы интерфейс не знал
про разрешение конкретного телефона.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from .. import adb, config, control, streaming
from ..devices import registry

router = APIRouter(prefix="/api/devices")
log = logging.getLogger("farm.screen")

SHELL_TIMEOUT = 30


def _require_online(serial: str):
    device = registry.get(serial)
    if device is None or not device.online:
        raise HTTPException(409, "устройство не в сети")
    return device


@router.get("/{serial}/stream")
def stream(serial: str, live: bool = False):
    _require_online(serial)
    return StreamingResponse(
        streaming.mjpeg(serial, live),
        media_type=f"multipart/x-mixed-replace; boundary={streaming.BOUNDARY}",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{serial}/frame")
def frame(serial: str):
    _require_online(serial)
    try:
        return StreamingResponse(iter([streaming.snapshot(serial)]), media_type="image/jpeg")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


@router.get("/{serial}/thumb")
def thumb(serial: str):
    """Превью для плитки фермы. Отдаётся из кэша, трансляцию не поднимает."""
    _require_online(serial)
    try:
        return StreamingResponse(iter([streaming.thumbnail(serial)]),
                                 media_type="image/jpeg",
                                 # URL кадра уникален (?t=), так что кэш не
                                 # подсунет старое — зато после перезагрузки
                                 # страницы последний кадр берётся из кэша.
                                 headers={"Cache-Control": "private, max-age=300"})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, str(e))


def _tap(serial, p):
    control.tap(serial, float(p["x"]), float(p["y"]))


def _long_tap(serial, p):
    control.long_tap(serial, float(p["x"]), float(p["y"]), float(p.get("duration", 0.8)))


def _swipe(serial, p):
    control.swipe(serial,
                  float(p["x1"]), float(p["y1"]),
                  float(p["x2"]), float(p["y2"]),
                  float(p.get("duration", 0.25)))


def _text(serial, p):
    control.text(serial, p.get("value", ""), clear=bool(p.get("clear")))


def _key(serial, p):
    # count — удержанная клавиша (Backspace): одним запросом, а не десятью
    for _ in range(max(1, min(int(p.get("count", 1)), 50))):
        control.key(serial, p["name"])


def _launch(serial, p):
    control.launch_app(serial, p["package"], p.get("activity"), bool(p.get("stop_first")))


def _stop(serial, p):
    control.stop_app(serial, p["package"])


def _url(serial, p):
    control.open_url(serial, p["url"])


def _unlock(serial, p):
    control.unlock(serial, p.get("pin"))


def _shell(serial, p):
    return {"ok": True, "output": adb.shell(serial, p["cmd"], timeout=SHELL_TIMEOUT)}


def _screen_off(serial, p):
    # 223 = KEYCODE_SLEEP: гасит экран, если он включён (повторно не включает).
    adb.shell(serial, "input keyevent 223", timeout=SHELL_TIMEOUT)


def _rotate(serial, p):
    """Книжная ↔ альбомная. Автоповорот выключаем: иначе датчик вернёт как было."""
    cur = adb.shell(serial, "settings get system user_rotation", timeout=SHELL_TIMEOUT).strip()
    nxt = "0" if cur in ("1", "3") else "1"
    adb.shell(serial, "settings put system accelerometer_rotation 0", timeout=SHELL_TIMEOUT)
    adb.shell(serial, f"settings put system user_rotation {nxt}", timeout=SHELL_TIMEOUT)
    control.forget_size(serial)   # размер экрана поменялся: тапы по старому кэшу попадали бы мимо
    return {"ok": True, "landscape": nxt == "1"}


ACTIONS = {
    "tap": _tap,
    "long_tap": _long_tap,
    "swipe": _swipe,
    "text": _text,
    "key": _key,
    "launch": _launch,
    "stop": _stop,
    "url": _url,
    "unlock": _unlock,
    "shell": _shell,
    "screen_off": _screen_off,
    "rotate": _rotate,
}


# Касания одного телефона идут строго по очереди (тап после свайпа не должен
# обгонять его), но каждый — в своей полосе: медленный жест не держит HTTP-ответ.
_lanes: dict[str, ThreadPoolExecutor] = {}
_lanes_lock = threading.Lock()
BACKGROUND_TYPES = {"swipe", "long_tap"}
BACKGROUND_MIN_SECONDS = 0.3   # короткий свайп быстрее, чем ждать очередь


def _lane(serial: str) -> ThreadPoolExecutor:
    with _lanes_lock:
        lane = _lanes.get(serial)
        if lane is None:
            lane = _lanes[serial] = ThreadPoolExecutor(1, thread_name_prefix=f"act-{serial}")
        return lane


def _run_background(handler, serial, payload):
    try:
        handler(serial, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("жест %s на %s не выполнился: %s", payload.get("type"), serial, e)


# HyperOS/MIUI без тумблера «USB-отладка (настройки безопасности)» режет
# нажатия adb; сырой стек пользователю ничего не говорит.
INPUT_BLOCKED_TEXT = ("Телефон не принимает нажатия. Включите в настройках для разработчиков "
                      "«USB-отладка (настройки безопасности)» и разрешите отладку заново")


@router.post("/{serial}/action")
def action(serial: str, response: Response, payload: dict = Body(...)):
    t0 = time.perf_counter()
    _require_online(serial)
    handler = ACTIONS.get(payload.get("type"))
    if handler is None:
        raise HTTPException(400, f"неизвестное действие: {payload.get('type')}")
    try:
        # Долгий жест подтверждаем сразу: человек уже видит результат на
        # экране, а ждать конца 0,8-секундного нажатия незачем.
        if payload.get("type") in BACKGROUND_TYPES and float(payload.get("duration", 0.25)) >= BACKGROUND_MIN_SECONDS:
            _lane(serial).submit(_run_background, handler, serial, payload)
            streaming.note_action(serial)
            response.headers["Server-Timing"] = f"act;dur={(time.perf_counter() - t0) * 1000:.1f}"
            return {"ok": True, "queued": True}
        result = _lane(serial).submit(handler, serial, payload).result()
    except KeyError as e:
        raise HTTPException(400, f"не хватает поля {e}")
    except (ValueError, TypeError) as e:
        # «x: "abc"», неизвестная клавиша — ошибка запроса, а не сервера.
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        if "inject_events" in str(e).lower():
            raise HTTPException(403, INPUT_BLOCKED_TEXT)
        raise HTTPException(500, str(e))
    streaming.note_action(serial)
    if _wakes_or_sleeps(payload):
        streaming.screen_refresh(serial, force=True)
    response.headers["Server-Timing"] = f"act;dur={(time.perf_counter() - t0) * 1000:.1f}"
    return result or {"ok": True}


SCREEN_KEYS = {"power", "wake", "sleep", "keycode_power", "keycode_wakeup", "keycode_sleep"}


def _wakes_or_sleeps(payload: dict) -> bool:
    """Действие, после которого экран мог загореться, погаснуть или открыться."""
    kind = payload.get("type")
    return kind in ("unlock", "screen_off") or (
        kind == "key" and str(payload.get("name", "")).lower() in SCREEN_KEYS)


@router.get("/{serial}/screenshot")
def screenshot(serial: str):
    """Скриншот в полном размере (PNG) — скачать файлом, а не кадр трансляции."""
    device = _require_online(serial)
    try:
        png = adb.exec_out(serial, ["screencap", "-p"], timeout=SHELL_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"скриншот не снялся: {e}")
    имя = f"{_safe(device.name)}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    # Заголовки — только latin-1: русское имя телефона кладём по RFC 5987,
    # а для старых браузеров — латинский запасной вариант.
    return Response(png, media_type="image/png", headers={"Content-Disposition":
                    f"attachment; filename=\"screenshot.png\"; filename*=UTF-8''{quote(имя)}"})


# ------------------------------------------------------------- видео экрана
# screenrecord пишет на сам телефон и сам останавливается через 3 минуты
# (ограничение Android). Остановка — SIGINT: тогда mp4 дописывается целым.
RECORD_LIMIT = 180
RECORD_ON_PHONE = "/sdcard/farm_screen.mp4"
RECORDINGS = config.ARTIFACTS_DIR / "recordings"
_records: dict[str, dict] = {}
_records_lock = threading.Lock()


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name or "phone")[:40]


@router.get("/{serial}/record")
def record_state(serial: str):
    with _records_lock:
        rec = _records.get(serial)
        if rec and rec["proc"].poll() is not None and not rec.get("stopping"):
            rec["ended"] = True   # упёрлось в 3 минуты — осталось забрать файл
        return {"recording": bool(rec), "since": rec["since"] if rec else None,
                "ended": bool(rec and rec.get("ended")), "limit": RECORD_LIMIT}


@router.post("/{serial}/record")
def record_start(serial: str):
    _require_online(serial)
    with _records_lock:
        if serial in _records:
            raise HTTPException(409, "запись уже идёт")
        try:
            proc = subprocess.Popen(
                [adb.ADB, "-s", serial, "shell", "screenrecord",
                 "--time-limit", str(RECORD_LIMIT), RECORD_ON_PHONE],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            raise HTTPException(500, "adb не найден")
        _records[serial] = {"proc": proc, "since": time.time()}
    return {"ok": True, "limit": RECORD_LIMIT}


@router.post("/{serial}/record/stop")
def record_stop(serial: str):
    with _records_lock:
        rec = _records.get(serial)
        if rec is None:
            raise HTTPException(409, "запись не идёт")
        if rec.get("stopping"):
            raise HTTPException(409, "запись уже сохраняется")
        rec["stopping"] = True
    try:
        if rec["proc"].poll() is None:
            adb.shell(serial, "pkill -INT screenrecord", timeout=SHELL_TIMEOUT)
            try:
                rec["proc"].wait(timeout=8)
            except subprocess.TimeoutExpired:
                rec["proc"].kill()
        time.sleep(0.5)   # телефону нужно мгновение, чтобы дописать mp4
        device = registry.get(serial)
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        имя = f"{_safe(device.name if device else serial)}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        adb.raw(["pull", RECORD_ON_PHONE, str(RECORDINGS / имя)], serial=serial, timeout=120)
        adb.shell(serial, f"rm -f {RECORD_ON_PHONE}", timeout=SHELL_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"видео не сохранилось: {e}")
    finally:
        with _records_lock:
            _records.pop(serial, None)
    return {"ok": True, "file": имя, "url": f"/api/recordings/{имя}"}


recordings_router = APIRouter(prefix="/api/recordings")


@recordings_router.get("/{name}")
def recording(name: str):
    path = (RECORDINGS / name).resolve()
    if RECORDINGS.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "видео не найдено")
    return FileResponse(path, media_type="video/mp4", filename=name)
