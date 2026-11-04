"""Regressions from the November audit: no physical device I/O."""
import asyncio
import base64
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException

from farm import config, scenarios
from farm.api import bulk, scenarios as run_api
from farm.devices import runner as R
from farm.recorder import save


@pytest.fixture(autouse=True)
def isolated_bulk(monkeypatch):
    # A fake queue need not have a running consumer; don't leak its Futures.
    monkeypatch.setattr(bulk, "_pending", set(), raising=False)


@pytest.fixture
def run(monkeypatch):
    sc = NS(key="audit", name="Audit", error="", params={})
    monkeypatch.setattr(scenarios, "get", lambda key: sc)
    monkeypatch.setattr(R.registry, "get", lambda s: NS(name=s, online=True))
    r = R.Runner()
    monkeypatch.setattr(r, "_queue_for", lambda serial: queue.Queue())
    monkeypatch.setattr(r, "_prune", lambda: None)
    monkeypatch.setattr(run_api, "runner", r)
    return r, sc


@pytest.mark.parametrize("account,status", [(None, "no_account"), ({"status": "banned"}, "banned")])
def test_busy_phone_does_not_bypass_account_preflight(monkeypatch, account, status):
    monkeypatch.setattr(scenarios.registry, "get", lambda s: NS(online=True, busy_job="previous"))
    monkeypatch.setattr(scenarios.accounts, "for_device", lambda *a: account)
    result = scenarios.preflight(NS(needs_accounts=["vk"]), ["audit"])
    assert result["devices"]["audit"]["status"] == status


def test_duplicate_serials_do_not_double_run(run):
    r, _ = run
    jobs = r.submit("audit", ["same", "same"], repeat=1)
    assert len(jobs) == 1


@pytest.mark.parametrize("repeat", [0, -1, 201, 1.5, True])
@pytest.mark.parametrize("trial", [False, True])
def test_invalid_repeat_rejected_before_any_job(run, repeat, trial):
    r, _ = run
    with pytest.raises(HTTPException) as err:
        run_api.run_scenario({"scenario": "audit", "serials": ["a", "b"],
                              "repeat": repeat, "trial": trial})
    assert err.value.status_code == 400
    assert not r.jobs and not r.trials


def test_trial_freezes_resolved_default_params(run):
    r, sc = run
    sc.params = {"target": {"default": "safe"}}
    jobs, trial = r.submit_trial("audit", ["first", "rest"])
    assert jobs[0].params == {"target": "safe"}
    sc.params = {"target": {"default": "changed"}}
    jobs[0].status = R.PASSED
    r._trial_settle(jobs[0])
    rest = [j for j in r.jobs.values() if j.serial == "rest"]
    assert rest[0].params == jobs[0].params


@pytest.mark.parametrize("code", [0, 2, "script stopped"])
def test_sys_exit_becomes_failed_job_and_releases_phone(tmp_path, monkeypatch, code):
    def run(ctx):
        raise SystemExit(code)
    sc = NS(key="audit", name="Audit", error="", params={}, recorded=False,
            path=str(tmp_path / "audit.py"), module=NS(run=run))
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(scenarios, "get", lambda key: sc)
    monkeypatch.setattr(R.registry, "get", lambda s: NS(rest=""))
    monkeypatch.setattr(R.registry, "acquire", lambda *a: True)
    released = []
    monkeypatch.setattr(R.registry, "release", lambda *a: released.append(a))
    monkeypatch.setattr(R.control, "clear_logcat", lambda *a: None)
    monkeypatch.setattr(R, "_collect_failure_artifacts", lambda *a: None)
    monkeypatch.setattr(R, "_record_failure", lambda *a: None)
    job = R.Job("audit", "audit", "Audit", "fake", "Fake", {})
    R._execute(job)
    assert job.status == R.FAILED and "SystemExit" in job.error
    assert job.finished_at is not None and released == [("fake", "audit")]


def test_worker_runs_next_job_after_sys_exit(tmp_path, monkeypatch):
    entered, resume, second_ran = (threading.Event() for _ in range(3))
    def script(ctx):
        if ctx.params["exit"]:
            entered.set()
            assert resume.wait(3)
            raise SystemExit(0)
        second_ran.set()
    sc = NS(key="audit", name="Audit", error="", params={}, recorded=False,
            path=str(tmp_path / "audit.py"), module=NS(run=script))
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(scenarios, "get", lambda key: sc)
    monkeypatch.setattr(R.registry, "get", lambda s: NS(name=s, online=True, rest=""))
    monkeypatch.setattr(R.registry, "acquire", lambda *a: True)
    monkeypatch.setattr(R.registry, "release", lambda *a: None)
    monkeypatch.setattr(R.control, "clear_logcat", lambda *a: None)
    monkeypatch.setattr(R, "_collect_failure_artifacts", lambda *a: None)
    monkeypatch.setattr(R, "_record_failure", lambda *a: None)
    r = R.Runner()
    r.WORKER_IDLE = 0.05
    first = r.submit("audit", ["SIM-001"], {"exit": True})[0]
    worker = r._workers["SIM-001"]
    try:
        assert entered.wait(3)
        second = r.submit("audit", ["SIM-001"], {"exit": False})[0]
    finally:
        resume.set()
    assert second_ran.wait(3)
    worker.join(3)
    assert not worker.is_alive()
    assert first.status == R.FAILED and second.status == R.PASSED


def test_failure_expected_image_reads_asset_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    assets = save.assets_dir("audit")
    assets.mkdir()
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aSxkAAAAASUVORK5CYII=")
    (assets / "button.png").write_bytes(png)
    (assets / "recipe.json").write_text('{"steps":[{"kind":"click","crop":"button.png"}]}')
    job = R.Job("audit", "audit", "Audit", "fake", "Fake", {})
    job.timeline = [{"i": 0, "status": "ok"}]
    art = tmp_path / "art"
    art.mkdir()
    R._mark_failed_step(job, NS(last_tap=None), art, NS(key="audit", recorded=True))
    assert (art / "99_expected.png").read_bytes() == png


@pytest.mark.parametrize("jitter", [None, [0, 0]])
def test_bulk_does_not_touch_busy_phone(monkeypatch, jitter):
    calls = []
    monkeypatch.setattr(bulk.registry, "get", lambda s: NS(online=True, busy_job="scenario"))
    monkeypatch.setitem(bulk.ACTIONS, "audit_action", lambda s, p: calls.append(s))
    result = bulk.bulk_action(["audit"], {"type": "audit_action"}, jitter=jitter, lead=None)
    assert calls == []
    assert result["results"]["audit"]["reason"] == "busy"


def test_delayed_bulk_rechecks_busy_state(monkeypatch):
    dev = NS(online=True, busy_job=None)
    calls = []
    monkeypatch.setattr(bulk.registry, "get", lambda s: dev)
    monkeypatch.setitem(bulk.ACTIONS, "audit_action", lambda s, p: calls.append(s))
    def enqueue(serial, delay, fn):
        from concurrent.futures import Future
        dev.busy_job = "new-scenario"
        fut = Future()
        try:
            fut.set_result(fn(serial))
        except Exception as exc:
            fut.set_exception(exc)
        return fut
    monkeypatch.setattr(bulk, "_enqueue", enqueue)
    result = bulk.bulk_action(["audit"], {"type": "audit_action"}, jitter=[0, 0], lead=None)
    assert calls == [] and result["results"]["audit"]["reason"] == "busy"


@pytest.mark.parametrize("operation", ["reboot", "install", "push"])
def test_bulk_file_and_reboot_operations_skip_busy_phones(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(bulk.registry, "get", lambda s: NS(online=True, busy_job="scenario"))
    calls = []
    monkeypatch.setattr(bulk.adb, "raw", lambda *a, **kw: calls.append(a) or "Success")
    monkeypatch.setattr(bulk.adb, "shell", lambda *a, **kw: calls.append(a) or "")
    async def upload(request, name):
        return tmp_path / name
    monkeypatch.setattr(bulk, "_upload", upload)
    monkeypatch.setattr(bulk, "_discard", lambda path: None)
    if operation == "reboot":
        result = bulk.bulk_reboot(["audit"])
    elif operation == "install":
        result = asyncio.run(bulk.bulk_install(None, "audit", "app.apk"))
    else:
        result = asyncio.run(bulk.bulk_push(None, "audit", "file.txt"))
    assert calls == [] and result["results"]["audit"]["reason"] == "busy"


def test_emergency_stop_cancels_between_dequeue_and_publication(monkeypatch):
    calls = []
    popped, resume = threading.Event(), threading.Event()
    class PausedQueue(queue.Queue):
        def get(self, *a, **kw):
            item = super().get(*a, **kw)
            if item is None:
                raise StopIteration
            popped.set()
            assert resume.wait(3)
            return item
    q = PausedQueue()
    monkeypatch.setattr(bulk, "_queues", {"audit": q})
    monkeypatch.setattr(bulk, "_last_due", {})
    monkeypatch.setattr(bulk, "_sleeping", {})
    fut = bulk._enqueue("audit", 0, lambda s: calls.append(s))
    def worker():
        try:
            bulk._worker("audit", q)
        except StopIteration:
            pass
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        assert popped.wait(3)
        dropped = bulk.drain_queues()
    finally:
        q.put(None)
        resume.set()
        t.join(3)
    assert not t.is_alive()
    assert calls == [] and fut.cancelled() and dropped == 1


def test_concurrent_enqueue_preserves_assigned_order(monkeypatch):
    blocked, resume, second_put = threading.Event(), threading.Event(), threading.Event()
    class PausedPutQueue(queue.Queue):
        def put(self, item, *a, **kw):
            if threading.current_thread().name == "audit-first":
                blocked.set()
                assert resume.wait(3)
            else:
                second_put.set()
            return super().put(item, *a, **kw)
    q = PausedPutQueue()
    monkeypatch.setattr(bulk, "_queues", {"audit": q})
    monkeypatch.setattr(bulk, "_last_due", {})
    first = threading.Thread(name="audit-first", target=lambda: bulk._enqueue("audit", 0, lambda s: "first"))
    first.start()
    with ThreadPoolExecutor(1) as pool:
        try:
            assert blocked.wait(3)
            second = pool.submit(bulk._enqueue, "audit", 0, lambda s: "second")
            second_put.wait(0.1)  # old code publishes the second command while first is paused
        finally:
            resume.set()
        second.result(timeout=3)
    first.join(3)
    a, b = q.get_nowait(), q.get_nowait()
    assert [a[1]("audit"), b[1]("audit")] == ["first", "second"]
    assert a[0] <= b[0]
