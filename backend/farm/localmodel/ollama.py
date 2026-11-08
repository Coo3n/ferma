"""Ollama по HTTP (127.0.0.1:11434): статус, список, скачивание с реальным прогрессом."""
from __future__ import annotations

import json
import os
import shutil
import threading
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:11434"
V1_URL = BASE + "/v1"
DOWNLOAD_URL = "https://ollama.com/download"
GB = 1024 ** 3

# Размеры — оценки по ollama.com/library (qwen2.5vl сверен по странице тегов).
CURATED = [
    {"id": "qwen2.5vl:3b", "title": "Qwen2.5-VL 3B", "download_gb": 3.2, "ram_gb_est": 6,
     "vision": True, "why": "Лёгкая модель, неплохо читает интерфейс и текст на скриншотах."},
    {"id": "gemma3:4b", "title": "Gemma 3 4B", "download_gb": 3.3, "ram_gb_est": 6,
     "vision": True, "why": "Компактная, подходит для слабых компьютеров; точность по мелкому тексту ниже."},
    {"id": "minicpm-v:8b", "title": "MiniCPM-V 8B", "download_gb": 5.5, "ram_gb_est": 10,
     "vision": True, "why": "Хорошо распознаёт текст на экране при умеренных требованиях."},
    {"id": "qwen2.5vl:7b", "title": "Qwen2.5-VL 7B", "download_gb": 6.0, "ram_gb_est": 10,
     "vision": True, "why": "Лучший баланс качества и размера для скриншотов интерфейса."},
    {"id": "llama3.2-vision:11b", "title": "Llama 3.2 Vision 11B", "download_gb": 7.8, "ram_gb_est": 14,
     "vision": True, "why": "Крупнее и точнее, но нужно больше памяти."},
    {"id": "gemma3:12b", "title": "Gemma 3 12B", "download_gb": 8.1, "ram_gb_est": 16,
     "vision": True, "why": "Высокое качество, для мощных компьютеров."},
]


def install_path() -> str:
    return os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")


def _get(path: str, timeout: float = 3.0) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def installed() -> bool:
    if shutil.which("ollama"):
        return True
    for p in (os.environ.get("LOCALAPPDATA", "") + r"\Programs\Ollama\ollama.exe",
              "/usr/local/bin/ollama", "/Applications/Ollama.app"):
        if p and os.path.exists(p):
            return True
    return False


def status() -> dict:
    out = {"installed": installed(), "running": False}
    try:
        out["version"] = _get("/api/version").get("version")
        out["running"] = True
        out["installed"] = True
    except Exception:
        pass
    return out


def list_models() -> list:
    try:
        data = _get("/api/tags")
    except Exception:
        return []
    return [{"name": m.get("name", ""), "size_gb": round(int(m.get("size") or 0) / GB, 2)}
            for m in data.get("models", [])]


def recommend(hw: dict) -> list:
    """Подходящие — выше; `fits` по измеренной памяти/диску. Без измерения fits=False."""
    ram = hw.get("ram_gb")
    disk = hw.get("disk_free_gb")
    vram = max([g.get("vram_gb") or 0 for g in hw.get("gpus", [])] or [0])
    mem = max(ram or 0, vram) if (ram or vram) else None
    out = []
    for m in CURATED:
        fits = bool(mem is not None and disk is not None
                    and m["ram_gb_est"] <= mem and m["download_gb"] * 1.2 <= disk)
        why = m["why"]
        if mem is None or disk is None:
            why += " Память или диск не удалось измерить."
        elif m["ram_gb_est"] > mem:
            why += f" Не хватает памяти: нужно около {m['ram_gb_est']} ГБ, есть {mem:g}."
        elif m["download_gb"] * 1.2 > disk:
            why += f" Не хватает места на диске: свободно {disk:g} ГБ."
        else:
            why += " Подходит вашему компьютеру."
        out.append({**m, "why": why, "fits": fits, "estimate": True})
    out.sort(key=lambda m: (not m["fits"], -m["download_gb"] if m["fits"] else m["download_gb"]))
    return out


# ---- задачи скачивания ----
_tasks: dict = {}
_lock = threading.Lock()


def _public(t: dict) -> dict:
    total, done = t["total"], t["completed"]
    pct = round(done * 100 / total, 1) if total else None
    st = t["state"]
    return {"state": st, "stage": t["stage"], "model": t["model"],
            "completed_bytes": done if total else None, "total_bytes": total or None,
            "percent": pct, "error": t["error"],
            "can_cancel": st in ("queued", "running"),
            "can_retry": st in ("error", "cancelled")}


def _run(tid: str, opener=None):
    t = _tasks[tid]
    t["state"] = "running"
    resp = None
    try:
        req = urllib.request.Request(BASE + "/api/pull", method="POST",
                                     data=json.dumps({"model": t["model"], "stream": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        resp = (opener or urllib.request.urlopen)(req, timeout=60)
        t["resp"] = resp
        for raw in resp:
            if t["cancel"]:
                break
            line = raw.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("error"):
                t["error"], t["state"] = str(ev["error"]), "error"
                return
            t["stage"] = ev.get("status") or t["stage"]
            if ev.get("total"):
                t["total"], t["completed"] = int(ev["total"]), int(ev.get("completed") or 0)
            if ev.get("status") == "success":
                t["state"] = "done"
                return
        t["state"] = "cancelled" if t["cancel"] else "error"
        if t["state"] == "error":
            t["error"] = "Загрузка прервалась до завершения"
    except Exception as e:
        if t["cancel"]:
            t["state"] = "cancelled"
        else:
            t["state"], t["error"] = "error", f"Не удалось скачать модель: {e}"
    finally:
        try:
            if resp is not None:
                resp.close()
        except Exception:
            pass


def start_pull(model: str, spawn=True) -> str:
    tid = uuid.uuid4().hex[:12]
    with _lock:
        _tasks[tid] = {"model": model, "state": "queued", "stage": "queued", "total": 0,
                       "completed": 0, "error": None, "cancel": False, "resp": None}
    if spawn:
        threading.Thread(target=_run, args=(tid,), daemon=True).start()
    return tid


def task(tid: str) -> dict | None:
    t = _tasks.get(tid)
    return _public(t) if t else None


def cancel(tid: str) -> dict | None:
    t = _tasks.get(tid)
    if not t:
        return None
    if t["state"] in ("queued", "running"):
        t["cancel"] = True
        if t["state"] == "queued":
            t["state"] = "cancelled"
        try:
            if t["resp"] is not None:
                t["resp"].close()   # закрытие потока отменяет скачивание
        except Exception:
            pass
    return _public(t)
