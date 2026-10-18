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
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
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


# Причина сбоя — коротким кодом: браузер переводит его в слова («телефон
# отключился», «мало места»), а сырой текст adb остаётся в подсказке.
# Порядок важен: «device offline» в тексте таймаута — всё равно «не в сети».
_REASONS = (
    ("unauthorized", ("unauthorized",)),
    ("offline", ("offline", "не в сети")),
    ("not_found", ("not found", "no devices", "no emulators")),
    ("timeout", ("таймаут", "timeout", "timed out")),
    ("no_space", ("insufficient_storage", "no space left", "enospc")),
    ("old_android", ("install_failed_older_sdk",)),
    ("downgrade", ("install_failed_version_downgrade",)),
    ("signature", ("install_failed_update_incompatible", "inconsistent_certificates",
                   "install_failed_shared_user_incompatible")),
    ("abi", ("no_matching_abis",)),
    ("blocked", ("install_failed_user_restricted", "install_failed_aborted",
                 "install_failed_verification_failure")),
    ("bad_apk", ("install_parse_failed", "install_failed_invalid_apk", "not a valid zip")),
    ("install_other", ("install_failed", "failure [")),
    ("no_access", ("read-only file system", "permission denied")),
)
_INSTALL_CODE = re.compile(r"\b(INSTALL_(?:FAILED|PARSE_FAILED)_[A-Z_]+)")


def failure(message: str) -> dict:
    """{ok: False, error, reason[, code]} по тексту исключения."""
    low = message.lower()
    reason = next((code for code, needles in _REASONS if any(n in low for n in needles)), "other")
    # Хвост важнее головы: у adb install суть («Failure [INSTALL_FAILED_…]»)
    # в конце, после длинной команды с путём к файлу.
    error = message if len(message) <= 300 else message[:110] + " … " + message[-180:]
    out = {"ok": False, "error": error, "reason": reason}
    m = _INSTALL_CODE.search(message)
    if m:
        out["code"] = m.group(1)
    return out


def _message(e: Exception) -> str:
    # У HTTPException текст в detail; str() дал бы «409: …».
    return str(getattr(e, "detail", None) or e)


def _skipped(asked: list[str] | None, targets: list[str]) -> dict:
    """Выбранные, но не в сети к моменту запроса, — тоже итог: иначе
    «готово на 36» молча теряло бы двоих, и повторить их было бы нельзя."""
    return {s: failure("не в сети") for s in dict.fromkeys(asked or []) if s not in targets}


def _summary(results: dict) -> dict:
    failed = sum(1 for r in results.values() if not r["ok"])
    return {"ok": failed == 0, "done": len(results) - failed, "failed": failed, "results": results}


def _each(serials: list[str], fn, asked: list[str] | None = None) -> dict:
    def one(serial):
        try:
            res = fn(serial)
            return serial, {"ok": True, **(res if isinstance(res, dict) else {})}
        except Exception as e:  # noqa: BLE001
            return serial, failure(_message(e))

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(serials))) as pool:
        results = dict(pool.map(one, serials))
    results.update(_skipped(asked, serials))
    return _summary(results)


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
# Действие, которое очередь уже достала и ждёт его срока. Раньше аварийная
# остановка его не видела: жест, спящий в разбросе, всё равно доходил.
_sleeping: dict[str, Future] = {}


def _worker(serial: str, q: queue.Queue) -> None:
    while True:
        due, fn, fut = q.get()
        _sleeping[serial] = fut
        wait = due - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _sleeping.pop(serial, None)
        if not fut.set_running_or_notify_cancel():
            continue   # аварийная остановка успела отменить
        try:
            fut.set_result(fn(serial))
        except Exception as e:  # noqa: BLE001
            log.warning("%s: отложенное действие не выполнилось: %s", serial, e)
            fut.set_exception(e)


def _enqueue(serial: str, delay: float, fn) -> Future:
    now = time.monotonic()
    with _queues_lock:
        q = _queues.get(serial)
        if q is None:
            q = _queues[serial] = queue.Queue()
            threading.Thread(target=_worker, args=(serial, q), daemon=True,
                             name=f"bulk-{serial}").start()
        due = max(now + delay, _last_due.get(serial, 0.0) + MIN_GAP)
        _last_due[serial] = due
    fut: Future = Future()
    q.put((due, fn, fut))
    return fut


def drain_queues() -> int:
    """Выбросить отложенные (с разбросом) действия, ещё не дошедшие до
    телефонов, — часть аварийной остановки фермы."""
    n = 0
    with _queues_lock:
        for q in _queues.values():
            while True:
                try:
                    _due, _fn, fut = q.get_nowait()
                except queue.Empty:
                    break
                fut.cancel()   # массовое действие ждёт итог — скажем «остановлено»
                n += 1
        for fut in list(_sleeping.values()):
            if fut.cancel():
                n += 1
    return n


# Сколько массовое действие с разбросом ждёт итог сверх самого разброса.
QUEUED_WAIT = 60.0


def _wait_queued(futures: dict[str, Future], hi: float) -> dict:
    """Итог по каждому телефону из очередей: окно «Действия» показывает,
    где не вышло и почему, а не «запланировано на 38»."""
    deadline = time.monotonic() + hi + QUEUED_WAIT
    results = {}
    for s, fut in futures.items():
        try:
            res = fut.result(timeout=max(0.0, deadline - time.monotonic()))
            results[s] = {"ok": True, **(res if isinstance(res, dict) else {})}
        except CancelledError:
            results[s] = {**failure("остановлено"), "reason": "stopped"}
        except FutureTimeout:
            results[s] = failure("таймаут: телефон не ответил")
        except Exception as e:  # noqa: BLE001
            results[s] = failure(_message(e))
    return results


@router.post("/action")
def bulk_action(serials: list[str] = Body(...), action: dict = Body(...),
                jitter: list[float] | None = Body(None), lead: str | None = Body(None)):
    """Синхронно (lead задан): ведущий выполняет сразу, ведомые — в своих
    очередях, ответ не ждёт ведомых. jitter=[lo, hi] — разброс по ведомым.
    Без lead — массовое действие: ждём всех (с разбросом — через те же
    очереди) и отдаём итог по каждому, включая выпавших из сети."""
    handler = ACTIONS.get(action.get("type"))
    if handler is None:
        raise HTTPException(400, f"неизвестное действие: {action.get('type')}")
    targets = _online(serials)
    run = lambda s: handler(s, action)  # noqa: E731
    if lead is None and not jitter:
        return _each(targets, run, serials)

    try:
        lo, hi = sorted(max(0.0, min(float(v), MAX_JITTER)) for v in (jitter or [0, 0])[:2])
    except (TypeError, ValueError):
        # [5] или ["abc"] раньше падали распаковкой — 500 вместо понятного 400.
        raise HTTPException(400, "jitter: два числа [от, до] в секундах")
    followers = [s for s in targets if s != lead]
    futures = {s: _enqueue(s, random.uniform(lo, hi), run) for s in followers}
    if lead is None:
        results = _wait_queued(futures, hi)
        results.update(_skipped(serials, targets))
        return _summary(results)
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
    return _each(_online(serials), lambda s: adb.raw(["reboot"], serial=s, timeout=30), serials)


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
    def install(serial):
        out = adb.raw(["install", "-r", "-g", str(apk)], serial=serial, timeout=INSTALL_TIMEOUT).strip()
        # Старый adb пишет «Failure [INSTALL_FAILED_…]» с кодом выхода 0.
        if "Failure [" in out or "INSTALL_FAILED" in out:
            raise RuntimeError(out[-300:])
        return {"output": out[-200:]}

    try:
        return _each(targets, install, serials.split(","))
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
        result = _each(targets, push, serials.split(","))
        result["path"] = dest
        return result
    finally:
        _discard(src)
