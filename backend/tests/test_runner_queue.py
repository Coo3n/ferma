"""Очередь раннера: журнал не теряет живые задачи, отмена не просыпается
через HOLD_TIMEOUT, частично неверный запуск не запускает никого."""
from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace

import pytest

from farm import config, scenarios
from farm import deviations as dv
from farm.devices import runner as R


def _job(jid, status):
    job = R.Job(id=jid, scenario_key="s", scenario_name="S",
                serial="emu", device_name="P", params={})
    job.status = status
    return job


def test_журнал_не_вытесняет_живые_задачи(monkeypatch):
    r = R.Runner()
    monkeypatch.setattr(config, "JOB_HISTORY", 3)
    for i, st in enumerate([R.PASSED, R.QUEUED, R.QUEUED, R.FAILED, R.QUEUED, R.QUEUED]):
        job = _job(f"j{i}", st)
        r.jobs[job.id] = job
        r.order.append(job.id)
    r._prune()
    # Выбрасываются только завершённые; очередь цела, даже сверх лимита.
    assert list(r.order) == ["j1", "j2", "j4", "j5"]
    assert set(r.jobs) == {"j1", "j2", "j4", "j5"}


def test_отмена_до_сброса_события_не_спит_до_таймаута(monkeypatch):
    """Отмена между check_cancel шага и сбросом _decided в _hold."""
    dv.deviations.clear()
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 30)
    monkeypatch.setattr(R.control, "save_screenshot", lambda *a: None)
    job = _job("hc1", R.RUNNING)
    R.runner.jobs[job.id] = job
    try:
        job._cancel.set()          # cancel() успел поставить флаг и событие...
        job._decided.set()         # ...а _hold сейчас его сбросит
        t0 = time.time()
        R._hold(job, "не найден элемент")
        assert time.time() - t0 < 5
        assert job.status == R.CANCELLING
    finally:
        R.runner.jobs.pop(job.id, None)
        dv.deviations.clear()


def test_неизвестный_телефон_не_запускает_остальных(monkeypatch):
    r = R.Runner()
    sc = SimpleNamespace(key="s", name="S", error="", params={})
    monkeypatch.setattr(scenarios, "get", lambda key: sc)
    monkeypatch.setattr(scenarios, "resolve_params", lambda sc, p: {})
    monkeypatch.setattr(R.registry, "get",
                        lambda s: SimpleNamespace(name=s) if s == "ok" else None)
    with pytest.raises(ValueError):
        r.submit("s", ["ok", "нет-такого"])
    assert r.jobs == {} and not r.order


def test_уходящий_воркер_не_теряет_задачу(monkeypatch):
    """Задача, положенная в момент выхода простаивающего потока, исполняется."""
    r = R.Runner()
    r.WORKER_IDLE = 0.05
    ran = []
    monkeypatch.setattr(R, "_execute", lambda job: ran.append(job.id))
    q = r._queue_for("emu")
    t = r._workers["emu"]
    t.join(2)
    assert not t.is_alive() and "emu" not in r._workers
    job = _job("w1", R.QUEUED)
    r.jobs[job.id] = job
    with r._lock:
        r._queue_for("emu").put(job.id)
    for _ in range(100):
        if ran:
            break
        time.sleep(0.02)
    assert ran == ["w1"]
