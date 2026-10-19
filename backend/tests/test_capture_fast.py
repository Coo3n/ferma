"""Быстрый путь кадра: JPEG с телефона и откат на старый."""
import base64
import io

from PIL import Image

from farm.control import capture

JPEG = io.BytesIO()
Image.new("RGB", (4, 4), "red").save(JPEG, format="JPEG")
JPEG = JPEG.getvalue()


class _Rpc:
    def __init__(self, result):
        self.result, self.calls = result, []

    def takeScreenshot(self, scale, quality):
        self.calls.append((scale, quality))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Dev:
    def __init__(self, result):
        self.jsonrpc = _Rpc(result)


def _patch(monkeypatch, dev):
    monkeypatch.setattr(capture, "size", lambda serial: (1080, 2400))
    monkeypatch.setattr(capture, "from_u2", lambda serial, action: _run(dev, action))


def _run(dev, action):
    try:
        return action(dev)
    except Exception:
        return None


def test_берёт_jpeg_с_телефона_без_pil(monkeypatch):
    dev = _Dev(base64.b64encode(JPEG).decode())
    _patch(monkeypatch, dev)
    assert capture.screenshot("s", max_width=540, quality=60) == JPEG
    scale, quality = dev.jsonrpc.calls[0]
    assert abs(scale - 0.5) < 1e-6 and quality == 60


def test_откат_если_телефон_ничего_не_вернул(monkeypatch):
    for bad in (None, "", RuntimeError("boom"), base64.b64encode(b"not a jpeg").decode()):
        _patch(monkeypatch, _Dev(bad))
        assert capture._device_jpeg("s", 480, 60) is None


def test_без_max_width_старый_путь(monkeypatch):
    dev = _Dev(base64.b64encode(JPEG).decode())
    _patch(monkeypatch, dev)
    monkeypatch.setattr(capture, "from_u2", lambda serial, action: Image.new("RGB", (8, 8)))
    out = capture.screenshot("s")
    assert out[:2] == b"\xff\xd8" and not dev.jsonrpc.calls
