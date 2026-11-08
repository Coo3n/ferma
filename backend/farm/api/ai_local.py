"""ИИ-мастер: железо фермы и локальная модель (Ollama). Установку Ollama не делаем сами."""
from __future__ import annotations

import importlib

from fastapi import APIRouter, Body, HTTPException

from ..localmodel import hardware, ollama
from ..vlm import settings

router = APIRouter(prefix="/api/ai", tags=["ai-local"])


@router.get("/hardware")
def get_hardware():
    return hardware.collect()


def _existing(p: str) -> str:
    from pathlib import Path
    q = Path(p)
    while not q.exists() and q != q.parent:
        q = q.parent
    return str(q)


@router.get("/local/status")
def local_status():
    st = ollama.status()
    out = {"ollama": st, "models": ollama.list_models() if st["running"] else [],
           "recommended": ollama.recommend(hardware.collect(_existing(ollama.install_path()))),
           "install_path": ollama.install_path()}
    if not st["running"]:
        out["download_url"] = ollama.DOWNLOAD_URL
        out["next_step"] = ("Скачайте и запустите Ollama" if not st["installed"]
                            else "Запустите Ollama")
        out["recheck"] = "/api/ai/local/status"
    return out


def _model(body: dict) -> str:
    m = str((body or {}).get("model") or "").strip()
    if not m or len(m) > 100 or any(c.isspace() for c in m):
        raise HTTPException(400, "Не указана модель")
    return m


@router.post("/local/pull")
def local_pull(body: dict = Body(...)):
    model = _model(body)
    info = next((m for m in ollama.CURATED if m["id"] == model), None)
    if body.get("confirm") is not True:
        raise HTTPException(400, "Подтвердите скачивание: покажите размер и папку установки и повторите с confirm=true")
    if not ollama.status()["running"]:
        raise HTTPException(409, "Ollama не запущена. Запустите её и нажмите «Проверить снова»")
    tid = ollama.start_pull(model)
    return {"task_id": tid, "model": model,
            "download_gb": info["download_gb"] if info else None,
            "install_path": ollama.install_path()}


@router.get("/local/tasks/{tid}")
def local_task(tid: str):
    t = ollama.task(tid)
    if not t:
        raise HTTPException(404, "Задача не найдена")
    return t


@router.post("/local/tasks/{tid}/cancel")
def local_cancel(tid: str):
    t = ollama.cancel(tid)
    if not t:
        raise HTTPException(404, "Задача не найдена")
    return t


def _probe():
    try:
        mod = importlib.import_module("farm.vlm.probe")
    except ImportError:
        return None
    fn = getattr(mod, "run", None)
    if not callable(fn):
        return None
    try:
        return fn(settings.get())
    except Exception as e:  # noqa: BLE001 — проба не должна ломать подключение
        return {"reachable": False, "detail": str(e)[:200]}


@router.post("/local/connect")
def local_connect(body: dict = Body(...)):
    model = _model(body)
    settings.save({"url": ollama.V1_URL, "model": model, "enabled": True})
    return {"url": ollama.V1_URL, "model": model, "probe": _probe()}
