"""Нажатия пульта: порядок на одном телефоне, долгие жесты не держат ответ."""
import threading
import time

import pytest
from fastapi import HTTPException, Response

from farm import control
from farm.api import screen as api


@pytest.fixture(autouse=True)
def онлайн(monkeypatch):
    monkeypatch.setattr(api, "_require_online", lambda serial: object())
    monkeypatch.setattr(api.streaming, "note_action", lambda serial: None)


def _post(serial, payload):
    resp = Response()
    return api.action(serial, resp, payload), resp


def test_тап_идёт_синхронно_и_с_замером(monkeypatch):
    calls = []
    monkeypatch.setitem(api.ACTIONS, "tap", lambda s, p: calls.append(p["x"]))
    result, resp = _post("S1", {"type": "tap", "x": 0.5, "y": 0.5})
    assert result == {"ok": True} and calls == [0.5]
    assert resp.headers["Server-Timing"].startswith("act;dur=")


def test_долгий_свайп_отвечает_сразу_а_следующий_тап_ждёт_его(monkeypatch):
    log = []
    done = threading.Event()

    def swipe(s, p):
        time.sleep(0.4)
        log.append("swipe")
        done.set()

    monkeypatch.setitem(api.ACTIONS, "swipe", swipe)
    monkeypatch.setitem(api.ACTIONS, "tap", lambda s, p: log.append("tap"))
    t0 = time.perf_counter()
    result, _ = _post("S2", {"type": "swipe", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "duration": 0.8})
    assert result["queued"] and time.perf_counter() - t0 < 0.2
    _post("S2", {"type": "tap", "x": 0.1, "y": 0.1})
    assert log == ["swipe", "tap"]   # порядок сохранён


def test_короткий_свайп_ждёт_завершения(monkeypatch):
    log = []
    monkeypatch.setitem(api.ACTIONS, "swipe", lambda s, p: log.append("swipe"))
    result, _ = _post("S3", {"type": "swipe", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "duration": 0.1})
    assert log == ["swipe"] and "queued" not in result


def test_ошибки_синхронного_действия_прежние(monkeypatch):
    def bad(s, p):
        raise ValueError("неизвестная клавиша: x")
    monkeypatch.setitem(api.ACTIONS, "key", bad)
    with pytest.raises(HTTPException) as e:
        _post("S4", {"type": "key", "name": "x"})
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        _post("S4", {"type": "нет такого"})
    assert e.value.status_code == 400


def test_поворот_сбрасывает_кэш_размера(monkeypatch):
    forgot = []
    monkeypatch.setattr(api.adb, "shell", lambda *a, **k: "0")
    monkeypatch.setattr(control, "forget_size", lambda s: forgot.append(s))
    api._rotate("S5", {})
    assert forgot == ["S5"]


def test_is_live_смотрят_или_только_что_смотрели():
    from farm import streaming
    src = streaming.source("S6")
    src._last_request = 0.0
    assert not streaming.is_live("S6")
    src._live_viewers = 1
    assert streaming.is_live("S6")
    src._live_viewers = 0
    src._last_request = time.time()
    assert streaming.is_live("S6")
    assert not streaming.is_live("нет такого")
