"""Менеджер аккаунтов: логины, пароли, прокси и привязка к телефону.

Сценарий не должен хранить логин в коде — он спрашивает у фермы
«какой аккаунт VK у этого телефона» через ``ctx.account("vk")``.
Хранится локально в accounts.json рядом с фермой.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from . import config

log = logging.getLogger("farm.accounts")

ACCOUNTS_FILE = config.DATA_DIR / "accounts.json"

# Статусы понятны без расшифровки: живой, нужен вход, заблокирован.
STATUSES = ("new", "active", "login", "banned")
# Ферма работает с четырьмя соцсетями; ключ — то, что пишут в ctx.account("vk").
PLATFORMS = ("vk", "inst", "tiktok", "tg")
FIELDS = ("platform", "login", "password", "phone", "proxy", "note", "serial", "status")

_lock = threading.RLock()
_items: list[dict] | None = None


# Пароли: файл читает только владелец. Права выставляются и при чтении —
# файл мог появиться раньше этой защиты с 644.
FILE_MODE = 0o600


def _restrict(path: Path) -> None:
    try:
        if path.exists() and (path.stat().st_mode & 0o777) != FILE_MODE:
            os.chmod(path, FILE_MODE)
    except OSError as e:
        log.warning("не удалось закрыть права на %s: %s", path.name, e)


def _load() -> list[dict]:
    global _items
    if _items is None:
        path = Path(ACCOUNTS_FILE)
        _restrict(path)
        try:
            data = json.loads(path.read_text("utf-8"))
            _items = data if isinstance(data, list) else []
        except FileNotFoundError:
            _items = []
        except Exception as e:  # noqa: BLE001
            # Битый файл не затираем первым же сохранением: откладываем копию.
            backup = path.with_name(f"{path.name}.broken-{int(time.time())}")
            try:
                os.replace(path, backup)
                _restrict(backup)
            except OSError:
                pass
            log.warning("accounts.json не читается (%s), копия: %s", type(e).__name__, backup.name)
            _items = []
    return _items


def _save() -> None:
    """Атомарно и сразу с правами 600: пароли не лежат открытыми ни мгновения."""
    path = Path(ACCOUNTS_FILE)
    tmp = path.with_name(path.name + ".tmp")
    try:
        data = json.dumps(_items, ensure_ascii=False, indent=2).encode("utf-8")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), FILE_MODE)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        # Только тип: текст исключения мог бы утащить содержимое в лог.
        log.warning("не удалось сохранить аккаунты: %s", type(e).__name__)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _clean(data: dict) -> dict:
    out = {k: str(data.get(k) or "").strip() for k in FIELDS if k in data}
    if "platform" in out:
        out["platform"] = out["platform"].lower()
        if out["platform"] not in PLATFORMS:
            raise ValueError(f"платформа должна быть одной из: {', '.join(PLATFORMS)}")
    if out.get("status") and out["status"] not in STATUSES:
        out["status"] = "new"
    return out


def all_accounts() -> list[dict]:
    with _lock:
        return [dict(a) for a in _load()]


def get(account_id: str) -> dict | None:
    with _lock:
        return next((dict(a) for a in _load() if a["id"] == account_id), None)


def create(data: dict) -> dict:
    item = {k: "" for k in FIELDS}
    item.update(_clean(data))
    item["status"] = item["status"] or "new"
    item["id"] = uuid.uuid4().hex[:10]
    item["updated"] = time.time()
    with _lock:
        _load().append(item)
        _save()
    return dict(item)


def update(account_id: str, data: dict) -> dict | None:
    with _lock:
        for a in _load():
            if a["id"] == account_id:
                a.update(_clean(data))
                a["updated"] = time.time()
                _save()
                return dict(a)
    return None


def delete(account_id: str) -> bool:
    with _lock:
        items = _load()
        before = len(items)
        items[:] = [a for a in items if a["id"] != account_id]
        if len(items) != before:
            _save()
            return True
    return False


def parse_lines(text: str, platform: str) -> list[dict]:
    """Строки «логин:пароль[:прокси]» или через ; / таб — как их отдают продавцы."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("\t", ";", ":"):
            if sep in line:
                parts = [p.strip() for p in line.split(sep)]
                break
        else:
            parts = [line]
        row = {"platform": platform, "login": parts[0]}
        if len(parts) > 1:
            row["password"] = parts[1]
        if len(parts) > 2:
            row["proxy"] = sep.join(parts[2:])
        rows.append(row)
    return rows


def import_lines(text: str, platform: str) -> list[dict]:
    return import_report(text, platform)["created"]


def import_report(text: str, platform: str) -> dict:
    """Импорт списка без дублей и мусора.

    Тот же логин той же платформы второй раз не заводится (повторная вставка
    списка или двойной клик давали двойников — два телефона в одном аккаунте
    = бан). Строка без пароля не импортируется, а называется номером: иначе
    в базе оставался аккаунт, которым не войти."""
    platform_key = platform.lower()
    with _lock:
        known = {a["login"].lower() for a in _load() if a["platform"] == platform_key}
    created, duplicates, bad = [], 0, []
    lineno = 0
    for raw in (text or "").splitlines():
        lineno += 1
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        rows = parse_lines(raw, platform)
        if not rows:
            continue
        row = rows[0]
        if not row.get("password"):
            bad.append(lineno)
            continue
        key = row["login"].lower()
        if key in known:
            duplicates += 1
            continue
        known.add(key)
        created.append(create(row))
    return {"created": created, "duplicates": duplicates, "bad_lines": bad}


def auto_bind(platform: str, serials: list[str]) -> int:
    """Раздать свободные аккаунты платформы телефонам, у которых такого ещё нет."""
    platform = platform.lower()
    with _lock:
        items = _load()
        taken = {a["serial"] for a in items if a["platform"] == platform and a["serial"]}
        free = [a for a in items if a["platform"] == platform and not a["serial"]
                and a["status"] != "banned"]
        bound = 0
        for serial in serials:
            if serial in taken or not free:
                continue
            acc = free.pop(0)
            acc["serial"] = serial
            acc["updated"] = time.time()
            bound += 1
        if bound:
            _save()
        return bound


def summary_for(serial: str) -> list[dict]:
    """Платформа и статус аккаунтов телефона — для плитки фермы. Без логинов
    и паролей: /api/devices читается каждые 3 секунды и логируется браузером."""
    with _lock:
        return [{"platform": a["platform"], "status": a["status"]}
                for a in _load() if a["serial"] == serial]


def for_device(serial: str, platform: str | None = None) -> dict | None:
    with _lock:
        for a in _load():
            if a["serial"] == serial and (platform is None or a["platform"] == platform.lower()):
                return dict(a)
    return None
