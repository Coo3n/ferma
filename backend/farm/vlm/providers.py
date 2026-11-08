"""Готовые адреса облачных нейросетей для окна «Подключить нейросеть».

Это только подсказки интерфейсу: адрес, страница получения ключа, пара
предлагаемых моделей. Настоящий список моделей всегда берётся у провайдера
(`/api/ai/models` с ключом), имена из `models_hint` — не истина, а стартовая
подсказка. Умеет ли модель картинки, говорит только реальная проба.
"""
from __future__ import annotations

PRESETS = [
    {"id": "openai", "title": "OpenAI (ChatGPT)", "base_url": "https://api.openai.com/v1",
     "key_url": "https://platform.openai.com/api-keys", "needs_key": True,
     "models_hint": ["gpt-4o-mini", "gpt-4o"], "note": ""},
    {"id": "claude", "title": "Claude (Anthropic)", "base_url": "https://api.anthropic.com/v1",
     "key_url": "https://console.anthropic.com/settings/keys", "needs_key": True,
     "models_hint": [], "note": "Картинки через этот вход не гарантированы — покажет проверка."},
    {"id": "gemini", "title": "Gemini (Google)", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "key_url": "https://aistudio.google.com/app/apikey", "needs_key": True,
     "models_hint": ["gemini-2.0-flash"], "note": ""},
    {"id": "qwen", "title": "Qwen (Alibaba)", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "key_url": "https://bailian.console.aliyun.com/?apiKey=1", "needs_key": True,
     "models_hint": ["qwen-vl-plus"], "note": "",
     "regions": [{"id": "cn", "title": "Китай", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
                 {"id": "intl", "title": "Международный",
                  "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"}]},
    {"id": "glm", "title": "GLM (Zhipu)", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "key_url": "https://open.bigmodel.cn/usercenter/apikeys", "needs_key": True,
     "models_hint": ["glm-4v-flash"], "note": ""},
    {"id": "kimi", "title": "Kimi (Moonshot)", "base_url": "https://api.moonshot.cn/v1",
     "key_url": "https://platform.moonshot.cn/console/api-keys", "needs_key": True,
     "models_hint": [], "note": ""},
    {"id": "deepseek", "title": "DeepSeek", "base_url": "https://api.deepseek.com",
     "key_url": "https://platform.deepseek.com/api_keys", "needs_key": True,
     "models_hint": ["deepseek-chat"], "note": "Обычно только текст: картинки не понимает."},
]


def presets() -> list:
    return [dict(p) for p in PRESETS]
