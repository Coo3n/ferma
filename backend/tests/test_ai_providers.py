"""Провайдеры нейросетей: пресеты, формы адресов в клиенте, заголовки. Сеть замокана."""
import json
import urllib.error
from types import SimpleNamespace

import pytest

from farm.api import ai
from farm.vlm import client, providers

URLS = {"openai": "https://api.openai.com/v1/chat/completions",
        "claude": "https://api.anthropic.com/v1/chat/completions",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "glm": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "kimi": "https://api.moonshot.cn/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/chat/completions"}


def test_presets_shape_and_route():
    ps = providers.presets()
    assert [p["id"] for p in ps] == list(URLS)
    for p in ps:
        assert p["base_url"].startswith("https://") and p["key_url"].startswith("https://")
        assert p["needs_key"] is True and isinstance(p["models_hint"], list)
    assert {r["id"] for r in ps[3]["regions"]} == {"cn", "intl"}
    assert ai.providers_route() == {"providers": ps}


@pytest.mark.parametrize("pid", list(URLS))
@pytest.mark.parametrize("tail", ["", "/", "//"])
def test_endpoint_and_models_url_from_same_base(monkeypatch, pid, tail):
    base = next(p["base_url"] for p in providers.PRESETS if p["id"] == pid)
    assert client.endpoint(base + tail) == URLS[pid]
    seen = []

    def fake(req, timeout=0):
        seen.append(req.full_url)
        return Body({"data": [{"id": "m1"}, {"nope": 1}]})
    monkeypatch.setattr(client.urllib.request, "urlopen", fake)
    cfg = SimpleNamespace(url=base + tail, key="k", timeout=5)
    assert client.list_models(cfg) == [{"id": "m1"}]
    assert seen == [URLS[pid].replace("/chat/completions", "/models")]


class Body:
    def __init__(self, data):
        self.data = json.dumps(data).encode()

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_anthropic_headers_only_for_anthropic():
    h = client._headers(SimpleNamespace(url="https://api.anthropic.com/v1", key="sk"))
    assert h["x-api-key"] == "sk" and h["Authorization"] == "Bearer sk" and "anthropic-version" in h
    h = client._headers(SimpleNamespace(url="https://api.openai.com/v1", key="sk"))
    assert "x-api-key" not in h


def _cfg(url):
    return SimpleNamespace(url=url, key="k", timeout=5, model="gpt-5", max_width=720)


def test_openai_retries_with_new_token_param(monkeypatch):
    bodies = []

    def fake(req, timeout=0):
        b = json.loads(req.data)
        bodies.append(b)
        if "max_tokens" in b:
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
        return Body({"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(client.urllib.request, "urlopen", fake)
    out = client.chat([{"role": "user", "content": "hi"}], cfg=_cfg("https://api.openai.com/v1"), max_tokens=20)
    assert out == "OK" and len(bodies) == 2
    assert "temperature" not in bodies[1] and bodies[1]["max_completion_tokens"] >= 1500


def test_other_hosts_do_not_retry_on_400(monkeypatch):
    calls = []

    def fake(req, timeout=0):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
    monkeypatch.setattr(client.urllib.request, "urlopen", fake)
    with pytest.raises(client.VlmError) as e:
        client.chat([{"role": "user", "content": "hi"}], cfg=_cfg("https://api.deepseek.com"))
    assert e.value.status == 400 and len(calls) == 1
