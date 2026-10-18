"""Массовые действия: одно и то же на всех выбранных телефонах разом.

На этом же стоит синхронное управление: жест на главном экране
уходит сюда со списком ведомых телефонов.
"""
from __future__ import annotations

import logging
import os
import queue
import random
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query, Request

from .. import adb
from ..devices import registry
from .screen import ACTIONS

router = APIRouter(prefix="/api/bulk")
log = logging.getLogger("farm.bulk")

WORKERS = 16
INSTALL_TIMEOUT = 300
PUSH_DIR = "/sdcard/Download"


def _online(serials: list[str]) -> list[str]:
    out = []
    for s in dict.fromkeys(serials or []):
        d = registry.get(s)
        if d is not None and d.online:
            out.append(s)
    if not out:
        raise HTTPException(409, "ни одного выбранного телефона в сети")
    return out


def _each(serials: list[str], fn) -> dict:
    def one(serial):
        try:
            res = fn(serial)
            return serial, {"ok": True, **(res if isinstance(res, dict) else {})}
        except Exception as e:  # noqa: BLE001
            return serial, {"ok": False, "error": str(e)[:300]}

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(serials))) as pool:
        results = dict(pool.map(one, serials))
    failed = sum(1 for r in results.values() if not r["ok"])
    return {"ok": failed == 0, "done": len(results) - failed, "failed": failed, "results": results}


# ------------------------------------------------------------ разброс
#
# 40 телефонов, тапнувших в одну миллисекунду, соцсеть видит как одного
# бота. С разбросом каждый ведомый повторяет жест через случайные lo..hi
# секунд — но отсчёт от МОМЕНТА НАЖАТИЯ, а не от конца предыдущего жеста.
# Раньше задержка шла после выполнения предыдущего: пять быстрых тапов —
# и ведомые отставали на ~10 с, отставание копилось. Теперь оно не больше
# hi, а порядок жестов на телефоне сохраняется: срок выполнения не раньше
# срока предыдущего жеста этого телефона.

MAX_JITTER = 10.0
MIN_GAP = 0.05          # между двумя жестами на одном телефоне
_queues: dict[str, queue.Queue] = {}
_last_due: dict[str, float] = {}
_queues_lock = threading.Lock()


def _worker(serial: str, q: queue.Queue) -> None:
    while True:
        due, fn = q.get()
        wait = due - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            fn(serial)
        except Exception as e:  # noqa: BLE001
            log.warning("%s: отложенное действие не выполнилось: %s", serial, e)


def _enqueue(serial: str, delay: float, fn) -> None:
    now = time.monotonic()
    with _queues_lock:
        q = _queues.get(serial)
        if q is None:
            q = _queues[serial] = queue.Queue()
            threading.Thread(target=_worker, args=(serial, q), daemon=True,
                             name=f"bulk-{serial}").start()
        due = max(now + delay, _last_due.get(serial, 0.0) + MIN_GAP)
        _last_due[serial] = due
    q.put((due, fn))


@router.post("/action")
def bulk_action(serials: list[str] = Body(...), action: dict = Body(...),
                jitter: list[float] | None = Body(None), lead: str | None = Body(None)):
    """Синхронно (lead задан): ведущий выполняет сразу, ведомые — в своих
    очередях, ответ не ждёт ведомых. jitter=[lo, hi] — разброс по ведомым.
    Без lead — массовое действие: ждём всех и отдаём итог по каждому."""
    handler = ACTIONS.get(action.get("type"))
    if handler is None:
        raise HTTPException(400, f"неизвестное действие: {action.get('type')}")
    targets = _online(serials)
    run = lambda s: handler(s, action)  # noqa: E731
    if lead is None and not jitter:
        return _each(targets, run)

    try:
        lo, hi = sorted(max(0.0, min(float(v), MAX_JITTER)) for v in (jitter or [0, 0])[:2])
    except (TypeError, ValueError):
        # [5] или ["abc"] раньше падали распаковкой — 500 вместо понятного 400.
        raise HTTPException(400, "jitter: два числа [от, до] в секундах")
    followers = [s for s in targets if s != lead]
    for s in followers:
        _enqueue(s, random.uniform(lo, hi), run)
    result = _each([lead], run) if lead in targets else {"ok": True, "done": 0, "failed": 0, "results": {}}
    result["queued"] = len(followers)
    return result


@router.post("/warm")
def bulk_warm(serials: list[str] = Body(..., embed=True)):
    """Поднять быстрые соединения (uiautomator2) и размер экрана заранее —
    перед синхронным режимом. Иначе первые жесты шли через медленный
    adb shell input, пока 40 соединений поднимались на ходу."""
    from ..control import geometry
    from ..devices import pool

    def warm(serial):
        try:
            geometry.size(serial)
            pool.get(serial)
        except Exception as e:  # noqa: BLE001
            log.debug("%s: прогрев не удался: %s", serial, e)

    targets = [s for s in dict.fromkeys(serials) if (registry.get(s) and registry.get(s).online)]
    for s in targets:
        threading.Thread(target=warm, args=(s,), daemon=True, name=f"warm-{s}").start()
    return {"ok": True, "warming": len(targets)}


# Список приложений меняется редко, а pm list на 40 телефонах — 40 вызовов adb.
PACKAGES_TTL = 60.0
_packages_cache: dict[str, tuple[float, list[str]]] = {}


def _packages(serial: str) -> list[str]:
    hit = _packages_cache.get(serial)
    if hit and time.monotonic() - hit[0] < PACKAGES_TTL:
        return hit[1]
    pkgs = adb.list_packages(serial, third_party_only=True)
    _packages_cache[serial] = (time.monotonic(), pkgs)
    return pkgs


@router.get("/packages")
def bulk_packages(serials: str = Query(...)):
    """Какие приложения стоят на выбранных телефонах и на скольких из них —
    чтобы выбрать приложение из списка по имени, а не вспоминать его пакет."""
    targets = _online(serials.split(","))
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(targets))) as pool_:
        lists = list(pool_.map(_packages, targets))
    counts: dict[str, int] = {}
    for pkgs in lists:
        for p in pkgs:
            counts[p] = counts.get(p, 0) + 1
    apps = sorted(({"package": p, "count": n} for p, n in counts.items()),
                  key=lambda a: (-a["count"], a["package"]))
    return {"total": len(targets), "apps": apps}


@router.post("/reboot")
def bulk_reboot(serials: list[str] = Body(..., embed=True)):
    return _each(_online(serials), lambda s: adb.raw(["reboot"], serial=s, timeout=30))


@router.post("/group")
def bulk_group(serials: list[str] = Body(...), group: str = Body("")):
    for s in serials:
        registry.set_group(s, group)
    return {"ok": True, "groups": registry.groups()}


@router.post("/tags")
def bulk_tags(serials: list[str] = Body(...), add: list[str] = Body([]), remove: list[str] = Body([])):
    """Добавить и/или снять теги у выбранных; остальные теги телефона не трогаем."""
    for s in dict.fromkeys(serials or []):
        if add:
            registry.add_tags(s, add)
        if remove:
            registry.remove_tags(s, remove)
    return {"ok": True, "tags": registry.all_tags()}


# Потолок загрузки: тело читается потоком на диск, а не в память, и всё
# равно ограничено — иначе один запрос забивает диск.
MAX_UPLOAD_BYTES = int(float(os.getenv("FARM_MAX_UPLOAD_MB", "1024")) * 1024 * 1024)
# Имя уходит в shell телефона (`am broadcast -d file://...`): только буквы,
# цифры, точка, дефис, подчёркивание — ни пробелов, ни кавычек, ни ; $ `.
_UNSAFE_NAME = re.compile(r"[^\w.\-]+")


def safe_name(name: str) -> str:
    base = Path(str(name or "").replace("\\", "/")).name
    base = _UNSAFE_NAME.sub("_", base).strip("._") or "file"
    return base[:120]


async def _upload(request: Request, name: str) -> Path:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ")
    tmp = Path(tempfile.mkdtemp(prefix="farm-")) / safe_name(name)
    size = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"файл больше {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ")
                fh.write(chunk)
        if not size:
            raise HTTPException(400, "пустой файл")
    except BaseException:
        _discard(tmp)
        raise
    return tmp


def _discard(path: Path) -> None:
    """Файл и его временную папку: mkdtemp на каждую загрузку иначе копится."""
    shutil.rmtree(path.parent, ignore_errors=True)


@router.post("/install")
async def bulk_install(request: Request, serials: str = Query(...), name: str = Query("app.apk")):
    """Тело запроса — сам APK; serials через запятую."""
    targets = _online(serials.split(","))
    apk = await _upload(request, name)
    try:
        return _each(targets, lambda s: {"output": adb.raw(
            ["install", "-r", "-g", str(apk)], serial=s, timeout=INSTALL_TIMEOUT).strip()[-200:]})
    finally:
        _discard(apk)


@router.post("/push")
async def bulk_push(request: Request, serials: str = Query(...), name: str = Query(...)):
    """Файл кладётся в «Загрузки» телефона — там его найдёт любое приложение."""
    targets = _online(serials.split(","))
    src = await _upload(request, name)
    dest = f"{PUSH_DIR}/{src.name}"
    def push(serial):
        adb.raw(["push", str(src), dest], serial=serial, timeout=INSTALL_TIMEOUT)
        # Без сканирования файл не виден в галерее до перезагрузки.
        adb.shell(serial, ["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                           "-d", f"file://{dest}"])

    try:
        result = _each(targets, push)
        result["path"] = dest
        return result
    finally:
        _discard(src)
