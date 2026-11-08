"""Локальная модель и железо: сеть и подпроцессы подменены."""
import io
import json

import pytest
from fastapi import HTTPException
from farm.api import ai_local
from farm.localmodel import hardware, ollama
from farm.vlm import settings

class _R:
    def __init__(self, code, data):
        self.status_code, self._d = code, data

    def json(self):
        return self._d


class _C:
    def _call(self, fn, *a, **k):
        try:
            return _R(200, fn(*a, **k))
        except HTTPException as e:
            return _R(e.status_code, {"detail": e.detail})

    def get(self, path):
        if path == "/api/ai/local/status":
            return self._call(ai_local.local_status)
        return self._call(ai_local.local_task, path.rsplit("/", 1)[1])

    def post(self, path, json=None):
        json = json or {}
        if path.endswith("/pull"):
            return self._call(ai_local.local_pull, json)
        if path.endswith("/connect"):
            return self._call(ai_local.local_connect, json)
        return self._call(ai_local.local_cancel, path.split("/")[-2])


client = _C()

def test_hardware_exact_flags(monkeypatch):
    monkeypatch.setattr(hardware, "_gpus", lambda: ([], False))
    monkeypatch.setattr(hardware, "_ram_bytes", lambda: None)
    hw = hardware.collect()
    assert hw["ram_gb"] is None and hw["exact"]["ram_gb"] is False
    assert hw["exact"]["gpus"] is False and hw["disk_free_gb"] is not None


def test_nvidia_parsed(monkeypatch):
    class R:
        returncode = 0
        stdout = "NVIDIA RTX 4070, 12282\n"
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: R())
    gpus, exact = hardware._gpus()
    assert exact and gpus == [{"name": "NVIDIA RTX 4070", "vram_gb": 12.0}]


def test_recommend_ranks_by_fit():
    rec = ollama.recommend({"ram_gb": 8, "disk_free_gb": 100, "gpus": []})
    assert rec[0]["fits"] and all(m["estimate"] for m in rec)
    assert not [m for m in rec if m["id"] == "gemma3:12b"][0]["fits"]
    assert all(not m["fits"] for m in ollama.recommend({"ram_gb": None, "disk_free_gb": None, "gpus": []}))


def test_status_not_running(monkeypatch):
    monkeypatch.setattr(ollama, "status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(hardware, "collect", lambda p=None: {"ram_gb": 16, "disk_free_gb": 50, "gpus": []})
    j = client.get("/api/ai/local/status").json()
    assert j["download_url"] == "https://ollama.com/download" and j["models"] == []
    assert j["recheck"] and j["install_path"]


def test_pull_requires_confirm(monkeypatch):
    monkeypatch.setattr(ollama, "status", lambda: {"installed": True, "running": True})
    assert client.post("/api/ai/local/pull", json={"model": "qwen2.5vl:3b"}).status_code == 400
    monkeypatch.setattr(ollama, "start_pull", lambda m: "t1")
    j = client.post("/api/ai/local/pull", json={"model": "qwen2.5vl:3b", "confirm": True}).json()
    assert j["task_id"] == "t1" and j["download_gb"] == 3.2 and j["install_path"]


def test_pull_ollama_down(monkeypatch):
    monkeypatch.setattr(ollama, "status", lambda: {"installed": True, "running": False})
    assert client.post("/api/ai/local/pull", json={"model": "x", "confirm": True}).status_code == 409


def _ndjson(*evs):
    return io.BytesIO(("\n".join(json.dumps(e) for e in evs) + "\n").encode())


def test_pull_progress_real_percent(monkeypatch):
    tid = ollama.start_pull("m", spawn=False)
    assert ollama.task(tid)["percent"] is None
    stream = _ndjson({"status": "pulling manifest"},
                     {"status": "pulling abc", "total": 200, "completed": 50},
                     {"status": "success"})
    ollama._run(tid, opener=lambda req, timeout: stream)
    t = ollama.task(tid)
    assert t["state"] == "done" and t["total_bytes"] == 200 and t["percent"] == 25.0
    assert not t["can_cancel"] and not t["can_retry"]


def test_pull_error_event_and_retry_flag():
    tid = ollama.start_pull("m", spawn=False)
    ollama._run(tid, opener=lambda r, timeout: _ndjson({"error": "pull model manifest: not found"}))
    t = ollama.task(tid)
    assert t["state"] == "error" and "not found" in t["error"] and t["can_retry"]


def test_cancel_closes_stream():
    tid = ollama.start_pull("m", spawn=False)
    closed = []

    class S:
        def close(self):
            closed.append(1)
    ollama._tasks[tid]["state"] = "running"
    ollama._tasks[tid]["resp"] = S()
    t = client.post(f"/api/ai/local/tasks/{tid}/cancel").json()
    assert closed
    assert ollama._tasks[tid]["cancel"] is True
    assert client.get("/api/ai/local/tasks/nope").status_code == 404


def test_connect_saves_and_probe_null(monkeypatch):
    saved = {}
    monkeypatch.setattr(settings, "save", lambda p: saved.update(p))
    monkeypatch.setattr(ai_local, "_probe", lambda: None)
    j = client.post("/api/ai/local/connect", json={"model": "qwen2.5vl:3b"}).json()
    assert saved["url"] == "http://127.0.0.1:11434/v1" and saved["model"] == "qwen2.5vl:3b"
    assert j["probe"] is None
    assert client.post("/api/ai/local/connect", json={}).status_code == 400
