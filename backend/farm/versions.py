"""Неизменяемые снимки шагов сюжета по хэшу и журнал ИИ-запусков (data/).

version = sha256(canonical_json(steps))[:12]. Снимок один раз записан — не меняется.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid

from . import config

_lock = threading.RLock()
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def version_of(steps) -> str:
    raw = json.dumps(steps, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _dir():
    return config.DATA_DIR / "ai_versions"


def _path(key: str):
    if not KEY_RE.match(key or ""):
        raise ValueError("недопустимый ключ сюжета")
    return _dir() / f"{key}.json"


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


def _read(path, default):
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def snapshot(key: str, steps: list, label: str = "") -> tuple[str, bool]:
    """Записать снимок; повтор тех же шагов — не новая версия."""
    ver = version_of(steps)
    with _lock:
        path = _path(key)
        data = _read(path, {})
        if ver in data:
            return ver, False
        data[ver] = {"created_at": time.time(), "label": str(label or "")[:80], "steps": steps}
        _write(path, data)
    return ver, True


def list_versions(key: str) -> list:
    data = _read(_path(key), {})
    rows = [{"version": v, "created_at": d.get("created_at"), "label": d.get("label", ""),
             "steps_count": len(d.get("steps") or [])} for v, d in data.items()]
    return sorted(rows, key=lambda r: r["created_at"] or 0, reverse=True)


def get_steps(key: str, version: str):
    d = _read(_path(key), {}).get(version)
    return None if d is None else d.get("steps")


# ---- журнал запусков data/ai_runs.json ----
def _runs_path():
    return config.DATA_DIR / "ai_runs.json"


def add_run(scenario_key: str, version: str, serial: str, job_id: str) -> dict:
    rec = {"run_id": uuid.uuid4().hex[:12], "job_id": job_id, "scenario_key": scenario_key,
           "version": version, "serial": serial, "started_at": time.time()}
    with _lock:
        runs = _read(_runs_path(), [])
        runs.append(rec)
        _write(_runs_path(), runs[-500:])
    return rec


def all_runs() -> list:
    return _read(_runs_path(), [])


def get_run(run_id: str):
    return next((r for r in all_runs() if r.get("run_id") == run_id), None)
