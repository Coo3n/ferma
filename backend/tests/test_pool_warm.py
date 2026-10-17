"""Фоновое подключение uiautomator2 для превью: не блокирует и не дублируется."""
import threading
import time

from farm.devices import pool


def test_warm_async_runs_once_in_background(monkeypatch):
    monkeypatch.setattr(pool, "_clients", {})
    monkeypatch.setattr(pool, "_failed_until", {})
    monkeypatch.setattr(pool, "_warming", set())
    started, release = [], threading.Event()

    def slow_get(serial, force=False):
        started.append(serial)
        release.wait(2)

    monkeypatch.setattr(pool, "get", slow_get)
    t0 = time.monotonic()
    pool.warm_async("s1")
    pool.warm_async("s1")          # второй вызов, пока первый ещё идёт
    assert time.monotonic() - t0 < 0.2   # вызывающий не ждёт подключения
    time.sleep(0.05)
    release.set()
    time.sleep(0.05)
    assert started == ["s1"]


def test_warm_async_skips_recent_failure(monkeypatch):
    monkeypatch.setattr(pool, "_clients", {})
    monkeypatch.setattr(pool, "_warming", set())
    monkeypatch.setattr(pool, "_failed_until", {"s1": time.time() + 60})
    called = []
    monkeypatch.setattr(pool, "get", lambda s, force=False: called.append(s))
    pool.warm_async("s1")
    time.sleep(0.05)
    assert called == []
