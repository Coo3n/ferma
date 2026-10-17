"""Кэш превью для плитки фермы.

Плитка опрашивает все устройства разом, поэтому здесь проверяется не
картинка, а экономия: сколько раз дошло до screencap.
"""
import threading
import time

import pytest

from farm import config
from farm.streaming import frames


@pytest.fixture(autouse=True)
def чистый_кэш(monkeypatch):
    frames._thumbs.clear()
    frames._sources.clear()
    monkeypatch.setattr(config, "THUMB_TTL", 10.0)


@pytest.fixture
def счётчик(monkeypatch):
    calls = []

    def fake(serial, max_width=None, quality=None):
        calls.append((serial, max_width, quality))
        return b"jpeg-" + serial.encode()

    monkeypatch.setattr(frames.control, "screenshot", fake)
    return calls


def test_первый_вызов_снимает_кадр(счётчик):
    assert frames.thumbnail("A") == b"jpeg-A"
    assert len(счётчик) == 1


def test_повтор_в_пределах_ttl_берётся_из_кэша(счётчик):
    frames.thumbnail("A")
    frames.thumbnail("A")
    frames.thumbnail("A")
    assert len(счётчик) == 1, "кэш не сработал — каждый запрос дошёл до adb"


def test_кадр_снимается_в_размере_плитки(счётчик):
    frames.thumbnail("A")
    _, max_width, quality = счётчик[0]
    assert max_width == config.THUMB_MAX_WIDTH
    assert quality == config.THUMB_QUALITY


def test_у_каждого_устройства_свой_кэш(счётчик):
    assert frames.thumbnail("A") == b"jpeg-A"
    assert frames.thumbnail("B") == b"jpeg-B"
    assert len(счётчик) == 2


def test_протухший_кэш_снимает_заново(счётчик, monkeypatch):
    monkeypatch.setattr(config, "THUMB_TTL", 0.0)
    frames.thumbnail("A")
    frames.thumbnail("A")
    assert len(счётчик) == 2


def test_параллельные_запросы_схлопываются_в_один_захват(monkeypatch):
    """Двадцать ячеек плитки не должны стать двадцатью вызовами screencap."""
    calls = []
    started = threading.Barrier(8)

    def slow(serial, max_width=None, quality=None):
        calls.append(serial)
        time.sleep(0.05)
        return b"jpeg"

    monkeypatch.setattr(frames.control, "screenshot", slow)

    def worker():
        started.wait()
        frames.thumbnail("A")

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"замок не удержал: захватов {len(calls)} вместо одного"


def test_идущая_трансляция_переиспользуется(monkeypatch):
    """Свежий кадр трансляции ужимается, а не снимается заново."""
    monkeypatch.setattr(frames.control, "screenshot",
                        lambda *a, **k: pytest.fail("полез в adb вместо кадра трансляции"))
    monkeypatch.setattr(frames, "_shrink", lambda data: b"small:" + data)

    src = frames.source("A")
    src.frame = b"big-frame"
    src._last_request = time.time()

    assert frames.thumbnail("A") == b"small:big-frame"


def test_старый_кадр_трансляции_не_берётся(счётчик):
    """Кадру больше трёх секунд верить нельзя — снимаем свежий."""
    src = frames.source("A")
    src.frame = b"stale"
    src._last_request = time.time() - 30

    assert frames.thumbnail("A") == b"jpeg-A"
    assert len(счётчик) == 1
