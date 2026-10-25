"""Учёт времени по причинам и флаг recent_scroll. Без телефона."""
import time

from farm import config
from farm.context import DeviceContext
from farm.devices import runner


def _ctx():
    return DeviceContext(serial="x", params={}, logger=lambda m: None,
                         cancel_check=lambda: False, artifacts_dir=None)


def test_sleep_и_settle_копятся_по_причинам(monkeypatch):
    from farm import control
    monkeypatch.setattr(control, "wait_stable",
                        lambda *a, **k: time.sleep(0.05) or True)
    ctx = _ctx()
    ctx.sleep(0.05)
    ctx._settle()
    t = ctx.time_by_reason
    assert t["sleep"] >= 0.05 and t["settle"] >= 0.05


def test_вложенное_время_не_считается_дважды(monkeypatch):
    ctx = _ctx()
    with ctx.spend("resolve"):
        ctx.sleep(0.1)
    t = ctx.time_by_reason
    assert t["sleep"] >= 0.1
    assert t.get("resolve", 0) < 0.05


def test_скролл_ставит_флаг_тап_сбрасывает(monkeypatch):
    from farm import control
    monkeypatch.setattr(control, "swipe", lambda *a, **k: None)
    monkeypatch.setattr(control, "tap", lambda *a, **k: None)
    ctx = _ctx()
    assert ctx.recent_scroll is False
    ctx.swipe(0.5, 0.7, 0.5, 0.3)
    assert ctx.recent_scroll is True
    ctx.tap(1, 1)
    assert ctx.recent_scroll is False


def test_settle_после_скролла_ждёт_рамку_цели(monkeypatch):
    from farm import control
    seen = {}
    monkeypatch.setattr(control, "wait_stable",
                        lambda *a, **k: seen.setdefault("stable", k) or True)
    monkeypatch.setattr(control, "wait_target_stable",
                        lambda serial, locate, **k: seen.setdefault("target", True))
    ctx = _ctx()
    ctx.recent_scroll = True
    ctx._settle({"text": "Ok"})
    assert "target" in seen and "stable" not in seen


def test_settle_после_скролла_без_цели_короткий_таймаут(monkeypatch):
    from farm import control
    seen = {}
    monkeypatch.setattr(control, "wait_stable",
                        lambda serial, **k: seen.update(k) or True)
    ctx = _ctx()
    ctx.recent_scroll = True
    ctx._settle()
    assert seen["timeout"] == min(config.SETTLE_TIMEOUT, config.SCROLL_SETTLE_TIMEOUT)


def test_job_to_dict_time_by_reason():
    job = runner.Job(id="j", scenario_key="k", scenario_name="n", serial="s",
                     device_name="d", params={})
    job.started_at = time.time() - 10
    job.finished_at = time.time()
    job.time_by_reason = {"sleep": 3.0, "settle": 2.0}
    t = job.to_dict()["time_by_reason"]
    assert t["sleep"] == 3.0 and t["settle"] == 2.0
    assert 4.5 < t["other"] < 5.5
    for k in ("wait_target", "resolve"):
        assert t[k] == 0.0
