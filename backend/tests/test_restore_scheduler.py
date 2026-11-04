"""A07: restoring a file must also replace the live scheduler's snapshot."""
import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import pytest

from farm import accounts, backup, config, schedule as S


def archive(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, value in entries.items():
            z.writestr(name, json.dumps(value))
    return buf.getvalue()


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(accounts, "_items", None)
    now = [datetime(2026, 11, 5, 0, 0)]
    device = SimpleNamespace(serial="PHONE", name="PHONE", online=True, enabled=True, busy_job=None, rest="")
    r = SimpleNamespace(submit=lambda *a, **kw: pytest.fail("restored finished slot must not run"))
    scheduler = S.Scheduler(tmp_path / "schedules.json", runner=r,
                            registry=SimpleNamespace(all=lambda: [device], get=lambda s: device),
                            clock=lambda: now[0])
    monkeypatch.setattr(S, "scheduler", scheduler)
    scheduler.create({"name": "OLD", "scenario": "demo", "window": {"from": "10:00", "to": "11:00"}})
    now[0] = datetime(2026, 11, 5, 12, 0)
    return scheduler, now


EMPTY = {"schedules": [], "state": {}, "since": {}}


def test_restored_empty_schedule_survives_tick(live):
    scheduler, _ = live
    backup.restore(archive({"data/schedules.json": EMPTY}))
    scheduler.tick()
    assert scheduler.all() == []
    assert json.loads(scheduler.path.read_text()) == EMPTY


def test_restore_retains_completed_slots_and_since(live):
    scheduler, now = live
    restored = S.normalize({"id": "restored", "name": "NEW", "scenario": "demo",
                            "window": {"from": "10:00", "to": "11:00"}})
    at = S.plan_times(restored, now[0].date(), "PHONE")[0]
    snapshot = {"schedules": [restored], "since": {"restored": 1},
                "state": {"restored|2026-11-05": {"PHONE": {str(int(at.timestamp())):
                          {"status": "started", "job": "already-ran", "note": ""}}}}}
    backup.restore(archive({"data/schedules.json": snapshot}))
    now[0] = at
    scheduler.tick()
    assert [s["name"] for s in scheduler.all()] == ["NEW"]
    assert scheduler.plan("restored")["phones"][0]["slots"][0]["status"] == "started"
    assert json.loads(scheduler.path.read_text()) == snapshot


def test_later_restore_failure_still_refreshes_written_schedule_and_accounts(live, monkeypatch):
    scheduler, _ = live
    accounts.create({"platform": "vk", "login": "OLD", "password": "pw"})
    real = backup.os.replace

    def fail_groups(src, dst):
        if dst.name == "groups.json":
            raise OSError("disk full")
        return real(src, dst)

    monkeypatch.setattr(backup.os, "replace", fail_groups)
    with pytest.raises(OSError):
        backup.restore(archive({"data/schedules.json": EMPTY, "data/accounts.json": [], "data/groups.json": {}}))
    scheduler.tick()
    assert json.loads(scheduler.path.read_text()) == EMPTY
    assert scheduler.all() == []
    assert accounts.all_accounts() == []


def test_failed_schedule_replacement_preserves_old_snapshot(live, monkeypatch):
    scheduler, _ = live
    before = scheduler.path.read_bytes()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(backup.os, "replace", fail)
    with pytest.raises(OSError):
        backup.restore(archive({"data/schedules.json": EMPTY}))
    assert scheduler.path.read_bytes() == before
    assert [s["name"] for s in scheduler.all()] == ["OLD"]


def test_tick_cannot_write_between_restore_replace_and_reload(live, monkeypatch):
    scheduler, _ = live
    replaced, release, tick_entered, tick_done = (threading.Event() for _ in range(4))
    real = backup.os.replace

    def pause(src, dst):
        result = real(src, dst)
        if dst == scheduler.path and src.name == "schedules.json.tmp":
            replaced.set()
            assert release.wait(3)
        return result

    def tick():
        tick_entered.set()
        scheduler.tick()
        tick_done.set()

    monkeypatch.setattr(backup.os, "replace", pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        restoring = pool.submit(backup.restore, archive({"data/schedules.json": EMPTY}))
        try:
            assert replaced.wait(3)
            ticking = pool.submit(tick)
            assert tick_entered.wait(3)
            assert not tick_done.wait(0.05)
        finally:
            release.set()
        restoring.result(timeout=3)
        ticking.result(timeout=3)
    assert json.loads(scheduler.path.read_text()) == EMPTY
