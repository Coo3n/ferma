"""Persistence regressions: complete APK backups and honest schedule failures."""
import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from test_request_limits import invoke

from farm import apklib, backup, config, schedule
from farm.api import bulk, jobs


def test_backup_restores_apks_with_index(tmp_path, monkeypatch):
    data, sc = tmp_path / "source", tmp_path / "scenarios"
    data.mkdir()
    sc.mkdir()
    (data / "apks").mkdir()
    apk = b"fake apk content; archive must preserve exact bytes"
    (data / "apks/org.example.app.apk").write_bytes(apk)
    (data / "apks.json").write_text(json.dumps({"org.example.app": {"name": "Example"}}))
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "SCENARIOS_DIR", sc)
    blob = backup.build()
    destination = tmp_path / "destination"
    destination.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", destination)
    backup.restore(blob)
    assert apklib.get("org.example.app") is not None
    assert apklib.path_of("org.example.app").read_bytes() == apk


def test_backup_build_rejects_unrestorable_size(tmp_path, monkeypatch):
    (tmp_path / "apks").mkdir()
    (tmp_path / "apks/org.example.app.apk").write_bytes(b"x" * 20)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(backup, "MAX_TOTAL", 10)
    with pytest.raises(ValueError):
        backup.build()


@pytest.mark.parametrize("name", ["data/apks/../outside.apk", "data/apks/a/b.apk",
                                 "data/apks/evil.txt", "data/apks/no_package.apk"])
def test_backup_rejects_unsafe_apk_paths(tmp_path, monkeypatch, name):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as z:
        z.writestr(name, b"fake")
    result = backup.restore(blob.getvalue())
    assert not result["restored"] and len(result["skipped"]) == 1


def fail_writes(monkeypatch, sched, operation):
    original = getattr(Path, operation)
    def fail(path, *a, **kw):
        if path == sched.path.with_suffix(".tmp"):
            raise OSError("fake disk failure")
        return original(path, *a, **kw)
    monkeypatch.setattr(Path, operation, fail)


@pytest.mark.parametrize("operation", ["write_text", "replace"])
@pytest.mark.parametrize("edit", ["create", "update", "delete", "toggle"])
def test_failed_schedule_edit_preserves_memory_and_disk(tmp_path, monkeypatch, edit, operation):
    sched = schedule.Scheduler(tmp_path / "schedules.json")
    item = sched.create({"name": "Original", "scenario": "audit"})
    original = json.loads(sched.path.read_text())
    fail_writes(monkeypatch, sched, operation)
    with pytest.raises(OSError):
        if edit == "create":
            sched.create({"name": "New", "scenario": "audit"})
        elif edit == "update":
            sched.update(item["id"], {"name": "Changed"})
        elif edit == "delete":
            sched.delete(item["id"])
        else:
            sched.toggle(item["id"])
    assert sched.all() == original["schedules"]
    assert sched._since == original["since"]
    assert json.loads(sched.path.read_text()) == original


def test_emergency_stop_drains_actions_even_if_pause_cannot_be_saved(tmp_path, monkeypatch):
    sched = schedule.Scheduler(tmp_path / "schedules.json")
    sched.create({"name": "Original", "scenario": "audit"})
    monkeypatch.setattr(schedule, "scheduler", sched)
    monkeypatch.setattr(jobs.runner, "cancel_all", lambda serial: 1)
    drained = []
    monkeypatch.setattr(bulk, "drain_queues", lambda: drained.append(True) or 1)
    fail_writes(monkeypatch, sched, "replace")
    with pytest.raises(OSError):
        jobs.cancel_all(everything=True)
    assert drained == [True]
    assert all(not s["enabled"] for s in sched.all())


def test_schedule_save_failure_is_safe_503(tmp_path, monkeypatch):
    from farm.api import schedule as api
    from farm import security
    from farm.server import create_app
    sched = schedule.Scheduler(tmp_path / "schedules.json")
    monkeypatch.setattr(api, "scheduler", sched)
    monkeypatch.setattr(api, "_check_scenario", lambda data: None)
    monkeypatch.setattr(security, "token", lambda: "")
    fail_writes(monkeypatch, sched, "write_text")
    status, _, body = asyncio.run(invoke(create_app(), path="/api/schedules",
        headers=[(b"content-type", b"application/json")],
        chunks=[json.dumps({"name": "Audit", "scenario": "audit"}).encode()]))
    assert status == 503
    assert b"fake disk failure" not in body
    assert sched.all() == []
