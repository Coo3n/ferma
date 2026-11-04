"""A01/A02: accepted stop wins over final success and deferred trial enqueueing."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from farm import config, schedule
from farm.api import bulk, jobs as api
from farm.devices import runner as R


@pytest.fixture
def run(monkeypatch, tmp_path):
    r = R.Runner()
    sc = SimpleNamespace(key="demo", name="Demo", error="", params={}, recorded=False,
                         path=str(tmp_path / "demo.py"), module=SimpleNamespace(run=lambda ctx: None))
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(R, "sweep_artifacts", lambda: None)
    monkeypatch.setattr(R.scenarios, "get", lambda key: sc)
    monkeypatch.setattr(R.scenarios, "resolve_params", lambda sc, p: dict(p or {}))
    monkeypatch.setattr(R.registry, "get", lambda s: SimpleNamespace(name=s, online=True, rest=""))
    monkeypatch.setattr(R.registry, "acquire", lambda *a: True)
    monkeypatch.setattr(R.registry, "release", lambda *a: None)
    monkeypatch.setattr(R.control, "clear_logcat", lambda *a: None)
    monkeypatch.setattr(r, "_queue_for", lambda s: SimpleNamespace(put=lambda jid: None))
    monkeypatch.setattr(api, "runner", r)
    monkeypatch.setattr(schedule, "scheduler", schedule.Scheduler(tmp_path / "schedules.json"))
    monkeypatch.setattr(bulk, "_queues", {})
    monkeypatch.setattr(bulk, "_sleeping", {})
    return r, sc


@pytest.mark.parametrize("finished", [False, True])
def test_cancel_final_step_prevents_success_and_followers(run, finished):
    r, sc = run
    jobs, trial = r.submit_trial("demo", ["A", "B", "C"])

    def last_step(ctx):
        assert r.cancel(jobs[0].id)
        assert jobs[0].status == R.CANCELLING
        if finished:
            raise R.Finished("done")

    sc.module.run = last_step
    R._execute(jobs[0])
    r._trial_settle(jobs[0])
    assert jobs[0].status == R.CANCELLED
    assert [j.serial for j in r.jobs.values()] == ["A"]


@pytest.mark.parametrize("everything", [False, True])
@pytest.mark.parametrize("forced", [False, True])
@pytest.mark.parametrize("clear_history", [False, True])
def test_stop_invalidates_selected_but_not_enqueued_trial(run, monkeypatch, everything, forced, clear_history):
    r, _ = run
    jobs, trial = r.submit_trial("demo", ["A", "B"], repeat=3)
    jobs[0].status = R.FAILED if forced else R.PASSED
    if forced:
        r._trial_settle(jobs[0])
    entering, resume = threading.Event(), threading.Event()
    original = r._trial_launch

    def pause(plan):
        entering.set()
        assert resume.wait(3)
        original(plan)

    monkeypatch.setattr(r, "_trial_launch", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(r.trial_release, trial.batch) if forced else pool.submit(r._trial_settle, jobs[0])
        try:
            assert entering.wait(3)
            if clear_history:
                r.clear_finished()
            assert api.cancel_all(serial=None, everything=everything)["ok"]
        finally:
            resume.set()
        task.result(timeout=3)
    assert not [j for j in r.jobs.values() if j.status in R.ACTIVE]
    assert r.trial_release(trial.batch) is None


def test_phone_stop_does_not_revive_in_trial(run):
    r, _ = run
    jobs, trial = r.submit_trial("demo", ["A", "B", "C"])
    r.cancel_all("B")
    jobs[0].status = R.PASSED
    r._trial_settle(jobs[0])
    assert sorted(j.serial for j in r.jobs.values()) == ["A", "C"]


def test_stop_after_fanout_cancels_enqueued_repeats(run):
    r, _ = run
    jobs, trial = r.submit_trial("demo", ["A", "B"], repeat=3)
    jobs[0].status = R.PASSED
    r._trial_settle(jobs[0])
    assert r.cancel_all() == 5
    assert not [j for j in r.jobs.values() if j.status in R.ACTIVE]
