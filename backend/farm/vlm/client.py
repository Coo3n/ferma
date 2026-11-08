"""Тонкий клиент к OpenAI-совместимому chat/completions с картинкой.

Подходит локальному серверу (LM Studio, llama.cpp, vLLM) и облачному API.
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
    status = None      # HTTP-код ответа сервера, если он был (chat/list_models)


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


def ask(image_bytes: bytes, prompt: str, cfg: "settings.Settings | None" = None,
        max_tokens: int = 300) -> str:
    cfg = cfg or settings.get()
    url = endpoint(cfg.url)
    jpeg = shrink(image_bytes, cfg.max_width)
    body = {
        "model": cfg.model,
        "temperature": 0,
        "max_tokens": int(max_tokens),
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


# ---- ниже: общий чат (текст и/или картинки) и список моделей; ask() выше не менялся ----

def _call(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        err = VlmError(f"нейросеть ответила ошибкой {e.code}")
        err.status = e.code
        raise err from None
    except (urllib.error.URLError, OSError) as e:
        raise VlmError(f"нейросеть недоступна: {_human(getattr(e, 'reason', e))}") from None
    except ValueError:
        raise VlmError("нейросеть прислала не JSON") from None


def _headers(cfg) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.key:
        h["Authorization"] = "Bearer " + cfg.key
        if urlsplit(cfg.url or "").hostname == "api.anthropic.com":
            h["x-api-key"] = cfg.key              # родной заголовок Anthropic, Bearer они не везде берут
            h["anthropic-version"] = "2023-06-01"
    return h


def _openai_variant(body: dict) -> dict:
    """Новые модели OpenAI (gpt-5, o-серия) не принимают max_tokens и temperature=0."""
    v = {k: x for k, x in body.items() if k not in ("temperature", "max_tokens")}
    v["max_completion_tokens"] = max(int(body.get("max_tokens", 0)), 1500)   # рассуждения съедают лимит
    return v


def chat(messages: list, cfg: "settings.Settings | None" = None, images: list | None = None,
         max_tokens: int = 1500) -> str:
    """Общий вызов chat/completions. messages — [{role, content: str}];
    images (bytes) прикрепляются к последнему сообщению пользователя."""
    cfg = cfg or settings.get()
    url = endpoint(cfg.url)
    msgs = [dict(m) for m in messages]
    if images:
        parts = [{"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(shrink(i, cfg.max_width)).decode("ascii")}}
            for i in images]
        for m in reversed(msgs):
            if m.get("role") == "user":
                m["content"] = parts + [{"type": "text", "text": str(m.get("content", ""))}]
                break
    body = {"model": cfg.model, "temperature": 0, "max_tokens": int(max_tokens), "messages": msgs}
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"), _headers(cfg), method="POST")
    try:
        return _text_of(_call(req, cfg.timeout))
    except VlmError as e:
        if e.status != 400 or urlsplit(url).hostname != "api.openai.com":
            raise
    req = urllib.request.Request(url, json.dumps(_openai_variant(body)).encode("utf-8"),
                                 _headers(cfg), method="POST")
    return _text_of(_call(req, cfg.timeout))


def list_models(cfg: "settings.Settings | None" = None) -> list:
    """GET {base}/models → [{id}]."""
    cfg = cfg or settings.get()
    base = endpoint(cfg.url)[:-len("/chat/completions")]
    req = urllib.request.Request(base + "/models", headers=_headers(cfg), method="GET")
    data = _call(req, cfg.timeout)
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise VlmError("сервер прислал список моделей в неожиданном формате")
    return [{"id": str(m["id"])} for m in items if isinstance(m, dict) and m.get("id")]
