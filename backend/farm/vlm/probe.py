"""Реальная проба сервера: текст и картинка (квадрат известного цвета)."""
from __future__ import annotations

import io
import time
from dataclasses import replace

from . import client

# (цвет RGB, допустимые слова в ответе)
_CASES = [((220, 30, 30), ("red", "красн")), ((30, 60, 220), ("blue", "син", "голуб"))]


def _image(rgb) -> bytes:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (256, 256), (255, 255, 255))
    ImageDraw.Draw(img).rectangle([64, 64, 192, 192], fill=rgb)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def run(cfg) -> dict:
    out = {"reachable": False, "text_ok": False, "vision": "unknown", "detail": "",
           "checked_at": time.time()}
    if not cfg.url:
        out["detail"] = "адрес нейросети не указан"
        return out
    # Первый запрос к локальной модели ждёт её загрузки в память — это минуты, а не секунды.
    # Поэтому пробе даём запас и один повтор после тайм-аута.
    slow = replace(cfg, timeout=max(cfg.timeout, 180))
    cfg = replace(cfg, timeout=max(cfg.timeout, 120))
    reply = None
    for attempt in (1, 2):
        try:
            reply = client.chat([{"role": "user", "content": "Reply with the single word OK."}],
                                cfg=slow, max_tokens=20)
            break
        except client.VlmError as e:
            if attempt == 1 and e.status is None and "дожда" in str(e):
                continue
            out["detail"] = str(e)
            out["reachable"] = e.status is not None
            return out
    out["reachable"] = True
    out["text_ok"] = bool(reply.strip())
    wrong = 0
    for rgb, words in _CASES:
        try:
            ans = client.chat([{"role": "user", "content":
                                "What color is the square in the picture? Answer with one word."}],
                              cfg=cfg, images=[_image(rgb)], max_tokens=20)
        except client.VlmError as e:
            if e.status is not None and 400 <= e.status < 500:
                out["vision"], out["detail"] = "no", f"сервер отверг изображение ({e.status})"
            else:
                out["detail"] = f"проба картинки не удалась: {e}"
            return out
        if any(w in ans.lower() for w in words):
            out["vision"], out["detail"] = "yes", "модель верно назвала цвет квадрата"
            return out
        wrong += 1
    out["vision"], out["detail"] = "no", "модель дважды неверно описала картинку"
    return out
