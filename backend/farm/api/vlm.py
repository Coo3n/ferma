"""Нейросеть-помощник: настройки, проверка связи, счётчик.

Ключ доступа наружу не отдаётся никогда — только маска. Значения из
переменных окружения важнее файла (`locked` в ответе), см. vlm/settings.py.
"""
from __future__ import annotations

import io
from dataclasses import replace

from fastapi import APIRouter, Body, HTTPException

from ..vlm import client, settings, usage

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
