"""Проба на одном телефоне живёт на сервере: прошла — остальные запускаются
сами, не прошла — ждут решения человека. Перезагрузка страницы план не теряет."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from farm import scenarios
from farm.api import scenarios as api
from farm.devices import runner as R


@pytest.fixture
def r(monkeypatch):
    """Раннер без потоков: задачи остаются в очереди, исход ставит тест."""
    run = R.Runner()
    sc = SimpleNamespace(key="vk", name="VK", error="", params={})
    monkeypatch.setattr(scenarios, "get", lambda key: sc)
    monkeypatch.setattr(scenarios, "resolve_params", lambda sc, p: dict(p or {}))
    offline = set()
    monkeypatch.setattr(R.registry, "get",
                        lambda s: None if s == "нет" else SimpleNamespace(name=f"Phone {s}",
                                                                         online=s not in offline))
    monkeypatch.setattr(run, "_queue_for", lambda serial: SimpleNamespace(put=lambda jid: None))
    monkeypatch.setattr(api, "runner", run)
    run.offline = offline
    return run


def _finish(r, job, status):
    """То, что делает воркер после _execute."""
    job.status = status
    r._trial_settle(job)


def _serials(r, batch):
    return sorted(j["serial"] for j in r.list_jobs(limit=100, batch=batch))


def test_проба_прошла_остальные_в_том_же_запуске(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2", "3"], "trial_serial": "2",
                            "params": {"n": 1}})
    batch = res["batch"]
    assert [j["serial"] for j in res["jobs"]] == ["2"]
    assert res["trial"]["state"] == R.TRIAL_RUNNING and res["trial"]["rest"] == 2
    assert _serials(r, batch) == ["2"]
    # Состояние пробы — в каждой задаче запуска: по нему рисуется «Запуски».
    assert r.list_jobs(batch=batch)[0]["trial"]["device_name"] == "Phone 2"

    _finish(r, r.get(res["jobs"][0]["id"]), R.PASSED)
    assert _serials(r, batch) == ["1", "2", "3"]
    t = r.trial(batch)
    assert t.state == R.TRIAL_STARTED and t.started == 2
    assert all(j["params"] == {"n": 1} for j in r.list_jobs(batch=batch))
    # Повторный итог (воркер + отмена) не удваивает остальных.
    _finish(r, r.get(res["jobs"][0]["id"]), R.PASSED)
    assert len(r.list_jobs(batch=batch)) == 3


def test_повторы_досылаются_пробному(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2"], "trial": True, "repeat": 3})
    assert res["jobs"][0]["serial"] == "1"   # trial: true — первый телефон
    _finish(r, r.get(res["jobs"][0]["id"]), R.PASSED)
    got = _serials(r, res["batch"])
    assert got.count("1") == 3 and got.count("2") == 3


def test_проба_упала_остальные_ждут_и_запускаются_по_кнопке(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2", "3"], "trial": True})
    batch = res["batch"]
    with pytest.raises(HTTPException) as e:          # проба ещё идёт
        api.trial_release(batch)
    assert e.value.status_code == 409

    _finish(r, r.get(res["jobs"][0]["id"]), R.FAILED)
    assert _serials(r, batch) == ["1"]
    trial = r.list_jobs(batch=batch)[0]["trial"]
    assert trial["state"] == R.TRIAL_FAILED and trial["job_status"] == R.FAILED

    r.offline.add("3")                                # пока думали, выпал из сети
    out = api.trial_release(batch)
    assert out["trial"]["state"] == R.TRIAL_FORCED
    assert out["trial"]["started"] == 1 and out["trial"]["skipped"] == 1
    assert _serials(r, batch) == ["1", "2"]
    with pytest.raises(HTTPException):                # второй клик — 409, не второй запуск
        api.trial_release(batch)
    assert _serials(r, batch) == ["1", "2"]


def test_отменённая_в_очереди_проба_не_запускает_остальных(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2"], "trial": True})
    assert r.cancel(res["jobs"][0]["id"])            # QUEUED → CANCELLED, воркер не увидит
    assert r.trial(res["batch"]).state == R.TRIAL_FAILED
    assert _serials(r, res["batch"]) == ["1"]


def test_не_запускать_остальных(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2"], "trial": True})
    batch = res["batch"]
    assert api.trial_cancel(batch)["trial"]["state"] == R.TRIAL_DROPPED
    # Проба доиграла и прошла — решение человека важнее.
    _finish(r, r.get(res["jobs"][0]["id"]), R.PASSED)
    assert _serials(r, batch) == ["1"]
    with pytest.raises(HTTPException):
        api.trial_release(batch)
    with pytest.raises(HTTPException):
        api.trial_cancel(batch)


def test_отмена_после_непрошедшей_пробы(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2"], "trial": True})
    _finish(r, r.get(res["jobs"][0]["id"]), R.FAILED)
    api.trial_cancel(res["batch"])
    with pytest.raises(HTTPException):
        api.trial_release(res["batch"])
    assert _serials(r, res["batch"]) == ["1"]


def test_неизвестный_телефон_не_запускает_и_пробу(r):
    with pytest.raises(HTTPException) as e:
        api.run_scenario({"scenario": "vk", "serials": ["1", "нет"], "trial": True})
    assert e.value.status_code == 400
    assert not r.jobs and not r.trials


def test_один_телефон_без_пробы(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1"], "trial": True})
    assert "trial" not in res and len(res["jobs"]) == 1
    assert not r.trials


def test_план_уходит_вместе_с_задачами(r):
    res = api.run_scenario({"scenario": "vk", "serials": ["1", "2"], "trial": True})
    _finish(r, r.get(res["jobs"][0]["id"]), R.FAILED)
    r.clear_finished()
    assert not r.trials


def test_воркер_подводит_итог_пробы(monkeypatch):
    """Настоящая очередь: после _execute воркер сам запускает остальных."""
    import time
    run = R.Runner()
    sc = SimpleNamespace(key="vk", name="VK", error="", params={})
    monkeypatch.setattr(scenarios, "get", lambda key: sc)
    monkeypatch.setattr(scenarios, "resolve_params", lambda sc, p: {})
    monkeypatch.setattr(R.registry, "get", lambda s: SimpleNamespace(name=s, online=True))
    ran = []

    def execute(job):
        ran.append(job.serial)
        job.status = R.PASSED

    monkeypatch.setattr(R, "_execute", execute)
    jobs, trial = run.submit_trial("vk", ["a", "b", "c"])
    for _ in range(200):
        if len(ran) == 3:
            break
        time.sleep(0.01)
    assert sorted(ran) == ["a", "b", "c"]
    assert trial.state == R.TRIAL_STARTED and trial.started == 2
