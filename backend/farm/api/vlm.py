"""Нейросеть-помощник: настройки, проверка связи, счётчик.

Ключ доступа наружу не отдаётся никогда — только маска. Значения из
переменных окружения важнее файла (`locked` в ответе), см. vlm/settings.py.
"""
from __future__ import annotations

import io
from dataclasses import replace

from fastapi import APIRouter, Body, HTTPException

from .. import config
from ..vlm import agent as vlm_agent, client, plan as vlm_plan, settings, usage

router = APIRouter(prefix="/api/vlm", tags=["vlm"])


def _state() -> dict:
    cfg = settings.get()
    return {**settings.public(), "used_today": usage.used_today(),
            "configured": bool(cfg.url)}


@router.get("")
def get_settings():
    return _state()


@router.get("/usage")
def get_usage():
    cfg = settings.get()
    return {"day": usage.today(), "used": usage.used_today(), "limit": cfg.max_per_day}


def _clean(payload: dict) -> dict:
    out: dict = {}
    if "enabled" in payload:
        out["enabled"] = bool(payload["enabled"])
    for name in ("url", "model"):
        if name in payload:
            out[name] = str(payload[name] or "").strip()
    if out.get("url"):
        try:
            client.endpoint(out["url"])
        except client.VlmError as e:
            raise HTTPException(400, str(e))
    key = payload.get("key")
    # Маска приходит обратно, если поле не трогали: ключ остаётся прежним.
    if isinstance(key, str) and not key.startswith("•"):
        out["key"] = key.strip()
    for name, lo, hi, kind in (("max_per_job", 0, 50, int), ("max_per_day", 0, 100000, int),
                               ("timeout", 1, 300, float), ("max_width", 160, 4000, int),
                               ("min_confidence", 0, 1, float)):
        if name in payload:
            try:
                v = kind(payload[name])
            except (TypeError, ValueError):
                raise HTTPException(400, f"поле {name} должно быть числом")
            if not lo <= v <= hi:
                raise HTTPException(400, f"поле {name}: допустимо от {lo} до {hi}")
            out[name] = v
    if out.get("enabled") and not (out.get("url") or settings.get().url):
        raise HTTPException(400, "сначала укажите адрес нейросети")
    return out


@router.put("")
def put_settings(payload: dict = Body(...)):
    patch = _clean(payload)
    # Сохранённый ключ привязан к сохранённому адресу: на чужой адрес он
    # не пойдёт (утечка ключа). Новый адрес — только вместе с новым ключом.
    new_url = patch.get("url")
    if new_url and new_url != settings.get().url and "key" not in patch:
        patch["key"] = ""
    settings.save(patch)
    return _state()


@router.post("/test")
def test_connection(payload: dict = Body(default={})):
    """Проверить связь тестовой картинкой. Квоту не тратит: это не работа
    фермы, а проверка человека. Подставленные в форме значения не сохраняются."""
    from PIL import Image
    cfg = settings.get()
    patch = _clean(payload or {})
    patch.pop("enabled", None)
    if patch.get("url") and patch["url"] != cfg.url and "key" not in patch:
        # Сохранённый ключ не отправляем на другой адрес: это утечка ключа.
        if cfg.key:
            raise HTTPException(400, "адрес изменён: введите ключ заново — "
                                     "сохранённый ключ на другой адрес не отправляется")
    cfg = replace(cfg, **patch)
    if not cfg.url:
        raise HTTPException(400, "сначала укажите адрес нейросети")
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (240, 240, 240)).save(buf, "JPEG")
    try:
        reply = client.ask(buf.getvalue(), "Reply with the single word OK.", cfg)
    except client.VlmError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"не получилось: {e}"}
    return {"ok": True, "reply": reply.strip()[:120]}


@router.post("/plan")
def make_plan(payload: dict = Body(...)):
    """Черновик сценария по описанию. Ничего не сохраняет и не запускает."""
    serial, task = payload.get("serial"), payload.get("task")
    if not serial:
        raise HTTPException(400, "не выбран телефон для снимка экрана")
    try:
        steps = vlm_plan.plan(serial, task)
    except vlm_plan.PlanError as e:
        raise HTTPException(400, str(e))
    return {"steps": steps, "recipe": vlm_plan.recipe_for(task, steps)}


@router.post("/agent/step")
def agent_step(payload: dict = Body(...)):
    """Одно предложенное действие. Телефон не меняет."""
    history = payload.get("history") or []
    try:
        out = vlm_agent.step(payload.get("serial"), payload.get("task"), history)
    except vlm_agent.AgentError as e:
        raise HTTPException(400, str(e))
    n = len(history) + 1
    return {**out, "step_no": n, "left": max(0, config.AGENT_MAX_STEPS - n)}


@router.post("/agent/do")
def agent_do(payload: dict = Body(...)):
    """Выполнить действие: сервер проверяет его заново."""
    try:
        return vlm_agent.do(payload.get("serial"), payload.get("action"))
    except vlm_agent.AgentError as e:
        raise HTTPException(400, str(e))


@router.post("/agent/recipe")
def agent_recipe(payload: dict = Body(...)):
    try:
        return vlm_agent.recipe(payload.get("task"), payload.get("history"))
    except vlm_agent.AgentError as e:
        raise HTTPException(400, str(e))
