"""Тонкий клиент к OpenAI-совместимому chat/completions с картинкой.

Подходит и локальному vLLM/SGLang с AutoGLM-Phone-9B, и облачному API.
Зависимостей нет (urllib). Остальной код зовёт `client.ask(image, prompt)` —
в тестах эту функцию подменяют, сеть не нужна.
"""
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import settings


class VlmError(RuntimeError):
    """Нейросеть не ответила. Текст — для человека, без секретов."""


def _human(reason) -> str:
    """Причина сбоя сети человеческими словами: «Errno 61» оператору ничего не
    говорит, а по тексту он понимает, что чинить — адрес или сам сервер."""
    text = str(reason).lower()
    if isinstance(reason, TimeoutError) or "timed out" in text:
        return "не дождались ответа"
    if "refused" in text:
        return "по этому адресу никто не отвечает"
    if "name or service not known" in text or "nodename nor servname" in text or "getaddrinfo" in text:
        return "такого адреса нет"
    if "unreachable" in text:
        return "адрес не достать из этой сети"
    return str(reason)


def endpoint(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
        raise VlmError("адрес нейросети должен начинаться с http:// или https://")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def shrink(image: bytes, max_width: int) -> bytes:
    """Уменьшить кадр: меньше трафика и токенов, а для поиска кнопки мелочи не нужны.
    Координаты ответа относительные (0–1000), так что масштаб им не мешает."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image))
        if img.width <= max_width and image[:2] == b"\xff\xd8":
            return image
        if img.width > max_width:
            img = img.resize((max_width, max(1, round(img.height * max_width / img.width))))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=80)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — не вышло уменьшить, шлём как есть
        return image


def _text_of(reply: dict) -> str:
    try:
        content = reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise VlmError("нейросеть ответила в неожиданном формате")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


def ask(image_bytes: bytes, prompt: str, cfg: "settings.Settings | None" = None) -> str:
    cfg = cfg or settings.get()
    url = endpoint(cfg.url)
    jpeg = shrink(image_bytes, cfg.max_width)
    body = {
        "model": cfg.model,
        "temperature": 0,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")}},
            {"type": "text", "text": prompt},
        ]}],
    }
    headers = {"Content-Type": "application/json"}
    if cfg.key:
        headers["Authorization"] = "Bearer " + cfg.key
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"), headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
            return _text_of(json.loads(resp.read().decode("utf-8", "replace")))
    except urllib.error.HTTPError as e:
        raise VlmError(f"нейросеть ответила ошибкой {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise VlmError(f"нейросеть недоступна: {_human(getattr(e, 'reason', e))}") from None
    except ValueError:
        raise VlmError("нейросеть прислала не JSON") from None
