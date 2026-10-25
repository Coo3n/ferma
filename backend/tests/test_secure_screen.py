"""Защищённый экран (FLAG_SECURE): распознавание кадра и пропуск слоёв зрения."""
import io
import time

from PIL import Image

from farm import deviations as dv
from farm import resolve
from farm.control import capture


def _png(color):
    b = io.BytesIO()
    Image.new("RGB", (40, 80), color).save(b, format="PNG")
    return b.getvalue()


def test_is_blank():
    assert capture.is_blank(Image.new("RGB", (100, 200), "black"))
    assert not capture.is_blank(Image.new("RGB", (100, 200), "white"))
    assert capture.is_blank(_png("black"))
    assert not capture.is_blank(_png("red"))


def test_screencap_failure_marks_secure(monkeypatch):
    monkeypatch.setattr(capture, "_secure_at", {})
    monkeypatch.setattr(capture, "from_u2", lambda s, a: None)
    monkeypatch.setattr(capture, "size", lambda s: (40, 80))
    monkeypatch.setattr(capture.adb, "screencap_png",
                        lambda s: b"Status: -1 (Failed to take screenshot)")
    data = capture.screenshot("s1")
    assert data[:2] == b"\xff\xd8"
    assert capture.is_secure("s1")


def test_normal_frame_clears_secure(monkeypatch):
    monkeypatch.setattr(capture, "_secure_at", {"s1": (True, time.time())})
    monkeypatch.setattr(capture, "from_u2", lambda s, a: None)
    monkeypatch.setattr(capture.adb, "screencap_png", lambda s: _png("red"))
    capture.screenshot("s1")
    assert not capture.is_secure("s1")


def test_secure_flag_expires(monkeypatch):
    monkeypatch.setattr(capture, "_secure_at", {"s1": (True, time.time() - 999)})
    assert not capture.is_secure("s1")


def test_resolve_skips_vision_when_secure(monkeypatch):
    monkeypatch.setattr(capture, "_secure_at", {"s1": (True, time.time())})

    class Ctx:
        serial = "s1"

        def screen_bytes(self):
            raise AssertionError("кадр на защищённом экране не нужен")

    assert resolve._by_ocr(Ctx(), "ok") is None
    assert resolve._by_template(Ctx(), "a.png") is None
    assert resolve.screen_secure(Ctx())


def test_secure_kind_registered():
    assert dv.SECURE in dv.KINDS
    dv.DeviationLog().record(kind=dv.SECURE, title="t")


def test_context_secure_cause_records_deviation(monkeypatch):
    from farm import context as cx
    log = dv.DeviationLog()
    monkeypatch.setattr(cx.dv, "deviations", log)

    class C:
        device_name, job_id, scenario_key, scenario_name = "p1", "j", "k", "n"
        lines = []

        def log(self, m):
            self.lines.append(m)

    out = cx.DeviceContext._secure_cause(C(), "цель не найдена")
    assert out.startswith("экран защищён от снимков") and "цель не найдена" in out
    assert any(d.kind == dv.SECURE for d in log._items.values())
