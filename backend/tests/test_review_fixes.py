"""Правки по ревью: осторожность по умолчанию там, где проверять нечем."""
import json
import time

import pytest
from fastapi import HTTPException

from farm import config, context as cx, deviations as dv, resolve
from farm.api import vlm as api
from farm.control import capture, diagnostics
from farm.vlm import locate, safety, settings, usage, learn
from tests.test_vlm import Ctx, GO, WHAT, включить, модель


def test_пустой_текст_под_точкой_отказ(monkeypatch):
    включить()
    модель(monkeypatch, GO)
    monkeypatch.setattr(locate, "_ocr_items", lambda image: [])
    assert locate.locate(Ctx('<hierarchy></hierarchy>'), WHAT) is None
    assert dv.VLM_DENIED in [d["kind"] for d in dv.deviations.list()]


def test_denylist_новые_слова():
    for w in ("Вывести", "withdraw", "Close account", "Оформить", "Сбросить", "Unlink", "Order now"):
        assert safety.irreversible(w), w


def test_ключ_не_уходит_на_чужой_url(monkeypatch):
    monkeypatch.setattr(settings, "get", lambda: settings.Settings(url="http://a.example/v1", key="SECRET"))
    with pytest.raises(HTTPException) as e:
        api.test_connection({"url": "http://evil.example/v1"})
    assert e.value.status_code == 400


def test_put_нового_url_сбрасывает_ключ(monkeypatch):
    saved = {}
    monkeypatch.setattr(settings, "get", lambda: settings.Settings(url="http://a.example/v1", key="SECRET"))
    monkeypatch.setattr(settings, "save", lambda p: saved.update(p))
    monkeypatch.setattr(api, "_state", lambda: {})
    api.put_settings({"url": "http://b.example/v1"})
    assert saved["key"] == ""


def test_чёрный_кадр_при_живом_дереве_не_защита(monkeypatch):
    from PIL import Image
    monkeypatch.setattr(capture, "_secure_at", {})
    monkeypatch.setattr(capture, "_device_jpeg", lambda *a: None)
    monkeypatch.setattr(capture, "from_u2", lambda s, a: Image.new("RGB", (40, 80)))
    monkeypatch.setattr(diagnostics, "dump_hierarchy", lambda s: "<node/>" * 10)
    capture.screenshot("s1")
    assert not capture.is_secure("s1")


def test_превью_не_пишет_флаг(monkeypatch):
    from PIL import Image
    monkeypatch.setattr(capture, "_secure_at", {})
    monkeypatch.setattr(capture, "_device_jpeg", lambda *a: None)
    monkeypatch.setattr(capture, "from_u2", lambda s, a: Image.new("RGB", (40, 80)))
    monkeypatch.setattr(diagnostics, "dump_hierarchy", lambda s: "")
    capture.screenshot("s1", max_width=200)
    assert not capture.is_secure("s1")


def test_лестница_отменяема(monkeypatch):
    class Stop(Exception):
        pass

    def fetch():
        raise RuntimeError("boom")

    def sleep(s):
        raise Stop()
    with pytest.raises(Stop):
        diagnostics.fetch_with_retry(fetch, lambda: None, sleep=sleep, recover_after=99)


def test_мёртвый_u2_кэшируется(monkeypatch):
    calls = []
    monkeypatch.setattr(diagnostics.u2pool, "get", lambda s: object())
    monkeypatch.setattr(diagnostics, "fetch_with_retry",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dead")))
    monkeypatch.setattr(diagnostics.u2pool, "drop", lambda s: None)
    monkeypatch.setattr(diagnostics.adb, "shell", lambda *a, **k: calls.append("shell"))
    monkeypatch.setattr(diagnostics.adb, "exec_out", lambda *a, **k: b"<x/>")
    diagnostics._dead_until.clear()
    diagnostics.dump_hierarchy("zz")
    monkeypatch.setattr(diagnostics, "fetch_with_retry",
                        lambda *a, **k: pytest.fail("лестница при кэше «мёртв»"))
    diagnostics.dump_hierarchy("zz")
    assert len(calls) == 2


def test_повтор_тапа_только_для_безопасного_селектора():
    class H:
        def __init__(self, layer, checkable=False):
            self.layer, self.checkable = layer, checkable
    c = object.__new__(cx.DeviceContext)
    assert c._tap_repeatable(H("selector"), [{"text": "Далее"}], None)
    assert not c._tap_repeatable(H("selector"), [{"text": "Отправить"}], None)
    assert not c._tap_repeatable(H("selector"), None, ["Купить"])
    assert not c._tap_repeatable(H("vlm"), [{"text": "Далее"}], None)
    assert not c._tap_repeatable(H("point"), None, None)
    assert not c._tap_repeatable(H("selector", True), None, ["Далее"])


def test_optional_depth_не_наследуется():
    c = object.__new__(cx.DeviceContext)
    c._optional_depth = 0
    c._cancel_check = lambda: False
    seen = []
    c.check_cancel = lambda: None
    c.attempt(lambda: c.attempt(lambda: seen.append(c._optional_depth)), optional=True)
    assert seen == [0]


def test_выученный_селектор_не_обходит_denylist(monkeypatch):
    class El:
        info = {"text": "Отправить", "contentDescription": ""}
    assert resolve._learned_denied(Ctx(), El())

    class Ok:
        info = {"text": "Далее"}
    assert not resolve._learned_denied(Ctx(), Ok())


def test_save_уникальный_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VLM_USAGE_FILE", tmp_path / "u.json")
    usage._data.clear() if hasattr(usage, "_data") else None
    usage._save()
    assert json.loads((tmp_path / "u.json").read_text()) == {}
    assert not list(tmp_path.glob("*.tmp"))
