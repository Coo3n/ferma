"""Библиотека APK фермы: приложения, которые сценарий ставит сам.

Один файл на приложение: data/apks/<пакет>.apk. Новый APK того же пакета
заменяет старый — сценарии ссылаются на пакет, а не на файл, и сразу
начинают ставить новую версию. Индекс — data/apks.json.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from . import apkinfo, config, control

log = logging.getLogger("farm.apklib")

PACKAGE_RE = re.compile(r"^[A-Za-z][\w]*(\.[A-Za-z][\w]*)+\Z")
# 40 телефонов × 100 МБ по USB разом кладут хаб: половина установок
# отваливается по таймауту. Остальные ждут своей очереди.
SLOTS = threading.BoundedSemaphore(4)
_lock = threading.Lock()

KNOWN = {"com.vkontakte.android": "VK", "com.instagram.android": "Instagram",
         "com.zhiliaoapp.musically": "TikTok", "com.ss.android.ugc.trill": "TikTok",
         "org.telegram.messenger": "Telegram"}
_NOISE = {"com", "org", "net", "ru", "app", "android", "mobile", "client"}

# Причины отказа установки — те же коды, что у массовой установки (bulk.failure).
REASON_WORDS = {
    "no_space": "на телефоне не хватило места",
    "signature": "на телефоне стоит другая сборка приложения — удалите её вручную "
                 "(данные приложения пропадут)",
    "old_android": "Android на телефоне слишком старый для этого приложения",
    "downgrade": "на телефоне уже стоит более новая версия",
    "abi": "приложение не подходит к этому телефону",
    "blocked": "телефон запретил установку — проверьте экран",
    "bad_apk": "файл приложения повреждён",
    "offline": "телефон отключился",
    "not_found": "телефон отключился",
    "timeout": "установка не уложилась во время",
}


class InstallFailed(Exception):
    """Установка не удалась; текст — для человека."""


def _dir() -> Path:
    return Path(config.DATA_DIR) / "apks"


def _index_path() -> Path:
    return Path(config.DATA_DIR) / "apks.json"


def path_of(package: str) -> Path:
    if not PACKAGE_RE.match(package or ""):
        raise ValueError(f"не похоже на приложение: {package!r}")
    return _dir() / f"{package}.apk"


def _load() -> dict:
    path = _index_path()
    try:
        data = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        # Не молчим: следующая запись перезапишет индекс, оставим копию.
        log.warning("индекс %s не читается — сохраняю копию .bad", path)
        try:
            shutil.copyfile(path, path.with_name(path.name + ".bad"))
        except OSError:
            pass
        return {}
    return data


def _save(index: dict) -> None:
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)


def name_of(package: str) -> str:
    entry = _load().get(package)
    if entry and entry.get("name"):
        return entry["name"]
    if package in KNOWN:
        return KNOWN[package]
    parts = [p for p in str(package).split(".") if p.lower() not in _NOISE] or [str(package)]
    word = parts[-1]
    return word[:1].upper() + word[1:]


def list_all() -> list[dict]:
    rows = [{"package": k, **v} for k, v in _load().items()]
    return sorted(rows, key=lambda r: r.get("name", "").lower())


def get(package: str) -> dict | None:
    entry = _load().get(package)
    return {"package": package, **entry} if entry else None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def add(src: Path, name: str = "") -> dict:
    """Положить APK в библиотеку (заменив прежний того же пакета)."""
    info = apkinfo.read(src)
    package = info["package"]
    try:
        dest = path_of(package)
    except ValueError:
        raise apkinfo.ApkError(f"в APK странное имя приложения: {package!r}") from None
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp)
        sha = _sha256(tmp)
        with _lock:
            os.replace(tmp, dest)
            index = _load()
            old = index.get(package) or {}
            index[package] = {
                "name": (name or "").strip()[:60] or old.get("name") or name_of(package),
                "version_name": info["version_name"],
                "version_code": info["version_code"],
                "min_sdk": info["min_sdk"],
                "size": dest.stat().st_size,
                "sha256": sha,
                "added": time.time(),
            }
            _save(index)
            return {"package": package, **index[package], "replaced": bool(old)}
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def rename(package: str, name: str) -> dict | None:
    name = (name or "").strip()[:60]
    with _lock:
        index = _load()
        if package not in index or not name:
            return None
        index[package]["name"] = name
        _save(index)
        return {"package": package, **index[package]}


def remove(package: str) -> bool:
    with _lock:
        index = _load()
        if package not in index:
            return False
        del index[package]
        _save(index)
        try:
            path_of(package).unlink()
        except (OSError, ValueError):
            pass
        return True


def usage() -> dict[str, int]:
    """Сколько сохранённых сценариев ссылается на каждое приложение."""
    from . import scenarios
    from .recorder import save
    out: dict[str, int] = {}
    for sc in scenarios.discover():
        recipe = save.load_recipe(sc.key) or {}
        used = {(s.get("args") or {}).get("package")
                for s in recipe.get("steps") or []
                if s.get("kind") in ("ensure_app", "if_phone")}
        for package in used - {None, ""}:
            out[package] = out.get(package, 0) + 1
    return out


def _words(text: str, path: str = "") -> str:
    if path:   # путь к APK содержит имя пакета («x.offline») — не причина отказа
        text = text.replace(path, "")
    from .api.bulk import failure   # здесь, не сверху: api импортирует apklib
    reason = failure(text)["reason"]
    return REASON_WORDS.get(reason, "телефон отказался ставить приложение")


def install(serial: str, package: str,
            check_cancel: Callable[[], None] = lambda: None) -> str:
    """Поставить приложение из библиотеки; ждёт свободного места в очереди."""
    if get(package) is None:
        raise InstallFailed(f"{name_of(package)} нет в библиотеке")
    while not SLOTS.acquire(timeout=0.5):
        check_cancel()
    try:
        check_cancel()
        apk = str(path_of(package))
        try:
            out = control.install(serial, apk).strip()
        except Exception as e:  # noqa: BLE001 — adb: таймаут, отключение
            raise InstallFailed(_words(str(e), apk)) from None
        if "Failure [" in out or "INSTALL_FAILED" in out:
            raise InstallFailed(_words(out, apk))
        return out
    finally:
        SLOTS.release()
