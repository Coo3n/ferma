"""Текстовый черновик: имя клавиши только из реальной таблицы (модель копировала «back|home|enter»)."""
from farm.vlm import review


def test_placeholder_key_name_is_dropped():
    assert review._text_step({"kind": "key", "args": {"name": "back|home|enter"}}) is None


def test_real_key_name_is_kept_lowercased():
    s = review._text_step({"kind": "key", "args": {"name": "HOME"}})
    assert s and s["args"]["name"] == "home"
