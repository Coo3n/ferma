"""ИИ-мастер сюжетов: /api/ai (контракт — docs/superpowers/specs/2026-11-06-ai-wizard-design.md).

Ключ модели в ответы и логи не попадает. Ответы модели разбираются строго.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import replace

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from .. import config, versions
from ..devices import registry
from ..devices.runner import runner
from ..recorder import save as saver, steps as schema
from ..vlm import analyze, client, plan as vlm_plan, probe, review, settings

router = APIRouter(prefix="/api/ai", tags=["ai"])
_cache: dict = {}      # request_id → ответ (идемпотентность)


def _remember(kind: str, rid, make):
    if not rid:
        return make()
    k = (kind, str(rid))
    if k not in _cache:
        if len(_cache) > 200:
            _cache.clear()
        _cache[k] = make()
    return _cache[k]


def _steps(raw) -> list:
    try:
        return schema.normalize_steps(raw)
    except schema.StepError as e:
        raise HTTPException(400, str(e))


def _cfg(url, model=None):
    """Настройки с подставленными url/model. Сохранённый ключ идёт только на сохранённый адрес."""
    saved = settings.get()
    url = (url or "").strip()
    if not url or url == saved.url:
        return replace(saved, model=model or saved.model), True
    return replace(saved, url=url, key="", model=model or ""), False


def _model_error(e: Exception) -> HTTPException:
    return HTTPException(502, str(e))


@router.post("/models")
def models(payload: dict = Body(...)):
    url = str(payload.get("url") or "").strip()
    key = payload.get("key")
    cfg, same = _cfg(url)
    if isinstance(key, str) and key.strip() and not key.startswith("•"):
        cfg = replace(cfg, key=key.strip())
    try:
        return {"models": client.list_models(cfg)}
    except client.VlmError as e:
        return {"models": [], "error": str(e)}


@router.post("/probe")
def probe_route(payload: dict = Body(default={})):
    cfg, same = _cfg(payload.get("url"), (payload.get("model") or "").strip() or None)
    saved = settings.get()
    res = probe.run(cfg)
    if cfg.url == saved.url and cfg.model == saved.model and cfg.url:
        settings.save({"vision": res["vision"]})
    return res


@router.post("/draft")
def draft(payload: dict = Body(...)):
    task = str(payload.get("task") or "").strip()
    if not task:
        raise HTTPException(400, "опишите задачу словами")
    cfg = settings.get()
    if not cfg.url:
        raise HTTPException(400, "сначала укажите адрес нейросети в настройках")
    answers = [str(a) for a in payload.get("clarify_answers") or []]
    serial = payload.get("serial")
    if serial and cfg.vision == "yes" and cfg.enabled:
        full = task + (". " + "; ".join(answers) if answers else "")
        try:
            steps = vlm_plan.plan(serial, full)
        except vlm_plan.PlanError as e:
            plan_failed = str(e)
        else:
            steps = _steps(steps)
            return {"status": "steps", "steps": steps, "notes": [], "needs_screen": False,
                    "version": versions.version_of(steps)}
    else:
        plan_failed = None
    try:
        out = review.draft_text(task, answers)
    except review.ModelReplyError as e:
        raise _model_error(e)
    if out["status"] == "steps":
        out["version"] = versions.version_of(out["steps"])
        if serial and cfg.vision != "yes":
            out["notes"].append("Модель не подтверждена как видящая картинки — черновик составлен только по тексту.")
        if plan_failed:
            out["notes"].append("По экрану не вышло — черновик по тексту. Для сложных задач нужна модель покрупнее.")
    return out


@router.post("/review")
def review_route(payload: dict = Body(...)):
    steps = _steps(payload.get("steps"))
    if not steps:
        raise HTTPException(400, "в сюжете нет шагов")
    rid = payload.get("request_id")

    def make():
        try:
            findings, dropped = review.review(steps)
        except review.ModelReplyError as e:
            raise _model_error(e)
        return {"request_id": rid, "version": versions.version_of(steps),
                "findings": findings, "dropped": dropped}
    return _remember("review", rid, make)


# ---------------------------------------------------------------- версии
@router.post("/versions")
def post_version(payload: dict = Body(...)):
    steps = _steps(payload.get("steps"))
    try:
        ver, created = versions.snapshot(str(payload.get("scenario_key") or ""), steps, payload.get("label") or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"version": ver, "created": created}


@router.get("/versions/{key}")
def get_versions(key: str):
    try:
        return versions.list_versions(key)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/versions/{key}/{version}")
def get_version(key: str, version: str):
    try:
        steps = versions.get_steps(key, version)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if steps is None:
        raise HTTPException(404, "такой версии нет")
    return {"steps": steps}


# ---------------------------------------------------------------- запуски
def _saved_steps(key: str) -> list:
    data = saver.load_recipe(key)
    if data is None:
        raise HTTPException(404, "сюжет не найден или не создан конструктором")
    return _steps(data.get("steps"))


def _run_view(rec: dict, current: str | None = None, detail: bool = False) -> dict:
    job = runner.get(rec["job_id"])
    if current is None:
        try:
            current = versions.version_of(_saved_steps(rec["scenario_key"]))
        except HTTPException:
            current = None
    d = {"run_id": rec["run_id"], "job_id": rec["job_id"], "version": rec["version"],
         "serial": rec["serial"], "started_at": rec["started_at"],
         "status": job.status if job else "unknown",
         "step_index": job.step_index if job else -1, "step_total": job.step_total if job else 0,
         "is_current": rec["version"] == current}
    if detail:
        dev = registry.get(rec["serial"])
        d["timeline"] = list(job.timeline) if job else []
        d["error"] = job.error if job else "задача больше не в журнале фермы"
        d["phone_state"] = "online" if dev is not None and dev.online else "offline"
    return d


@router.post("/run")
def run_route(payload: dict = Body(...)):
    key, version = str(payload.get("scenario_key") or ""), str(payload.get("version") or "")
    serial = str(payload.get("serial") or "")
    if not (key and version and serial):
        raise HTTPException(400, "нужны scenario_key, version и serial")
    steps = _saved_steps(key)
    if versions.version_of(steps) != version:
        raise HTTPException(409, "сюжет изменён")
    risky = review.risky_steps(steps)
    if risky and not payload.get("confirm_risky"):
        return JSONResponse({"detail": "в сюжете есть рискованные шаги — нужно подтверждение", "risky": risky},
                            status_code=409)
    versions.snapshot(key, steps, "запуск")
    try:
        jobs = runner.submit(key, [serial], step_shots=True)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rec = versions.add_run(key, version, serial, jobs[0].id)
    return {"run_id": rec["run_id"], "job_id": rec["job_id"]}


@router.get("/runs")
def runs(scenario_key: str = ""):
    rows = [r for r in versions.all_runs() if not scenario_key or r["scenario_key"] == scenario_key]
    cur: dict = {}
    out = []
    for r in reversed(rows):
        k = r["scenario_key"]
        if k not in cur:
            try:
                cur[k] = versions.version_of(_saved_steps(k))
            except HTTPException:
                cur[k] = None
        out.append(_run_view(r, cur[k]))
    return out


def _rec(run_id: str) -> dict:
    rec = versions.get_run(run_id)
    if rec is None:
        raise HTTPException(404, "запуск не найден")
    return rec


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    return _run_view(_rec(run_id), detail=True)


@router.post("/runs/{run_id}/stop")
def run_stop(run_id: str):
    rec = _rec(run_id)
    return {"ok": runner.cancel(rec["job_id"]), "run_id": run_id}


@router.post("/analyze")
def analyze_route(payload: dict = Body(...)):
    rec = _rec(str(payload.get("run_id") or ""))
    rid = payload.get("request_id")
    steps = versions.get_steps(rec["scenario_key"], rec["version"])
    if steps is None:
        raise HTTPException(404, "снимок версии этого запуска не найден")
    job = runner.get(rec["job_id"])
    if job is None:
        raise HTTPException(404, "запуск больше не в журнале фермы")

    def make():
        from .jobs import load_report, load_shots
        rep = load_report(job.id, runner.job_dict(job))
        shots = load_shots(job.id, rep)
        try:
            res = analyze.run(steps, rep, shots, job.error, timeline=[dict(t) for t in job.timeline],
                              status=str(job.status))
        except review.ModelReplyError as e:
            raise _model_error(e)
        return {"request_id": rid, "version": rec["version"], **res}
    return _remember("analyze", rid, make)


# ---------------------------------------------------------------- железо
def _ram_gb():
    try:
        if sys.platform == "win32":
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                            ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong), ("f", ctypes.c_ulonglong)]
            ms = MS()
            ms.l = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return round(ms.total / 2**30, 1)
        elif os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo") as f:
                return round(int(f.readline().split()[1]) / 2**20, 1)
        else:
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _gpus() -> list:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        txt = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:  # noqa: BLE001
        return []
    out = []
    for line in txt.splitlines():
        name, _, mem = line.partition(",")
        if name.strip():
            g = {"name": name.strip()}
            if mem.strip().isdigit():
                g["vram_gb"] = round(int(mem) / 1024, 1)
            out.append(g)
    return out


# GET /api/ai/hardware живёт в api/ai_local.py (localmodel.hardware) — дубль убран.


# ==================== провайдеры нейросетей (api/ai-providers) ====================
@router.get("/providers")
def providers_route():
    from ..vlm import providers
    return {"providers": providers.presets()}
# ==================== конец блока провайдеров ====================
