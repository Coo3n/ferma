"""Barrier-based probes of bulk ownership and consistent APK snapshots."""
import hashlib
import importlib
import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from farm import apklib, backup, config
from farm.api import bulk


@pytest.mark.parametrize("fail", [False, True])
def test_bulk_owns_phone_until_handler_finishes(tmp_path, monkeypatch, fail):
    module = importlib.import_module("farm.devices.registry")
    for name in ("LABELS_FILE", "GROUPS_FILE", "TAGS_FILE"):
        monkeypatch.setattr(module, name, tmp_path / name)
    reg = module.Registry()
    phone = module.Device(serial="SIM-001", state="device")
    reg._devices[phone.serial] = phone
    monkeypatch.setattr(bulk, "registry", reg)
    entered, resume = threading.Event(), threading.Event()
    def handler(serial, payload):
        entered.set()
        assert resume.wait(3)
        if fail:
            raise RuntimeError("audit command failed")
    monkeypatch.setitem(bulk.ACTIONS, "audit_lease", handler)
    with ThreadPoolExecutor(1) as pool:
        result = pool.submit(bulk.bulk_action, [phone.serial], {"type": "audit_lease"}, None, None)
        try:
            assert entered.wait(3)
            during = reg.acquire(phone.serial, "scenario")
            if during:
                reg.release(phone.serial, "scenario")
        finally:
            resume.set()
        response = result.result(timeout=3)
    assert during is False, "a scenario acquired the phone during a bulk command"
    assert response["ok"] is (not fail)
    assert reg.acquire(phone.serial, "after")
    reg.release(phone.serial, "after")
    assert phone.available


@pytest.mark.parametrize("mutation", ["replace", "remove"])
def test_backup_apk_index_and_bytes_are_one_snapshot(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path / "scenarios")
    package = "org.example.app"
    apk = apklib.path_of(package)
    apk.parent.mkdir()
    old = b"old APK bytes"
    apk.write_bytes(old)
    (tmp_path / "apks.json").write_text(json.dumps({package: {
        "name": "Example", "sha256": hashlib.sha256(old).hexdigest(), "version_name": "1"}}))
    source = tmp_path / "update.apk"
    source.write_bytes(b"new APK bytes")
    monkeypatch.setattr(apklib.apkinfo, "read", lambda path: {
        "package": package, "version_name": "2", "version_code": 2, "min_sdk": 23})
    captured, resume, attempted, mutated = (threading.Event() for _ in range(4))
    original = zipfile.ZipFile.write
    def write(z, path, name=None, *args, **kwargs):
        result = original(z, path, name, *args, **kwargs)
        if name == "data/apks.json":
            captured.set()
            assert resume.wait(3)
        return result
    monkeypatch.setattr(zipfile.ZipFile, "write", write)
    def mutate():
        attempted.set()
        try:
            return apklib.add(source) if mutation == "replace" else apklib.remove(package)
        finally:
            mutated.set()
    with ThreadPoolExecutor(2) as pool:
        exported = pool.submit(backup.build)
        try:
            assert captured.wait(3)
            update = pool.submit(mutate)
            assert attempted.wait(3)
            mutated.wait(0.1)  # old exporter permits mutation after writing the index
        finally:
            resume.set()
        blob = exported.result(timeout=3)
        update.result(timeout=3)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        index = json.loads(z.read("data/apks.json"))
        assert f"data/apks/{package}.apk" in z.namelist()
        content = z.read(f"data/apks/{package}.apk")
        assert index[package]["sha256"] == hashlib.sha256(content).hexdigest()


def test_restore_serializes_apk_rename_after_its_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    package = "org.example.app"
    (tmp_path / "apks").mkdir()
    apklib.path_of(package).write_bytes(b"local")
    (tmp_path / "apks.json").write_text(json.dumps({package: {"name": "Local"}}))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("data/apks.json", json.dumps({package: {"name": "Restored"}}))
        z.writestr(f"data/apks/{package}.apk", b"restored")
    writing, resume, renamed = (threading.Event() for _ in range(3))
    original = backup.os.replace
    def replace(src, dst):
        if str(dst) == str(tmp_path / "apks.json") and threading.current_thread().name.startswith("audit-restore"):
            writing.set()
            assert resume.wait(3)
        return original(src, dst)
    monkeypatch.setattr(backup.os, "replace", replace)
    def rename():
        try:
            return apklib.rename(package, "Renamed")
        finally:
            renamed.set()
    with ThreadPoolExecutor(1, thread_name_prefix="audit-restore") as restore_pool, ThreadPoolExecutor(1) as edit_pool:
        restore = restore_pool.submit(backup.restore, buffer.getvalue())
        try:
            assert writing.wait(3)
            edit = edit_pool.submit(rename)
            renamed.wait(0.1)
        finally:
            resume.set()
        restore.result(timeout=3)
        edit.result(timeout=3)
    assert apklib.get(package)["name"] == "Renamed"
    assert apklib.path_of(package).read_bytes() == b"restored"
