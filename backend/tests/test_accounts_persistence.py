"""A03–A06/A09: durable account edits, concurrent imports and exact secrets."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from farm import accounts


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", path)
    monkeypatch.setattr(accounts, "_items", None)
    return path


@pytest.mark.parametrize("operation", ["create", "update", "delete", "delete_many", "unbind", "bind", "import"])
def test_failed_write_preserves_memory_and_disk(store, monkeypatch, operation):
    bound = accounts.create({"platform": "vk", "login": "bound", "password": "secret", "serial": "A"})
    accounts.create({"platform": "vk", "login": "free", "password": "secret"})
    before = accounts.all_accounts()
    disk = store.read_bytes()

    def fail(*args):
        raise OSError("disk full secret")

    monkeypatch.setattr(accounts.os, "replace", fail)
    actions = {
        "create": lambda: accounts.create({"platform": "vk", "login": "new"}),
        "update": lambda: accounts.update(bound["id"], {"password": "changed"}),
        "delete": lambda: accounts.delete(bound["id"]),
        "delete_many": lambda: accounts.delete_many([bound["id"]]),
        "unbind": lambda: accounts.unbind_many([bound["id"]]),
        "bind": lambda: accounts.auto_bind("vk", ["B"]),
        "import": lambda: accounts.import_report("first:pw\nsecond:pw", "vk"),
    }
    with pytest.raises(OSError) as exc:
        actions[operation]()
    assert "secret" not in str(exc.value)
    assert accounts.all_accounts() == before
    assert store.read_bytes() == disk
    assert not list(store.parent.glob("*.tmp"))
    accounts._items = None
    assert accounts.all_accounts() == before


def test_save_without_unix_fchmod(store, monkeypatch):
    monkeypatch.delattr(accounts.os, "fchmod", raising=False)
    item = accounts.create({"platform": "vk", "login": "windows", "password": "pw"})
    accounts._items = None
    assert accounts.get(item["id"])["password"] == "pw"


def test_autobind_one_account_per_distinct_phone(store):
    for login in ("first", "second", "third"):
        accounts.create({"platform": "vk", "login": login})
    assert accounts.auto_bind("vk", ["A", "A", "B"]) == 2
    assert [a["serial"] for a in accounts.all_accounts()] == ["A", "B", ""]


def test_concurrent_import_has_one_winner(store, monkeypatch):
    barrier = threading.Barrier(2)
    parse = accounts.parse_lines

    def together(*args):
        barrier.wait(timeout=3)
        return parse(*args)

    monkeypatch.setattr(accounts, "parse_lines", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(accounts.import_report, "Same:pw", "VK") for _ in range(2)]
        reports = [f.result(timeout=4) for f in tasks]
    assert [a["login"] for a in accounts.all_accounts()] == ["Same"]
    assert sorted(len(r["created"]) for r in reports) == [0, 1]
    assert sum(r["duplicates"] for r in reports) == 1


def test_manual_password_whitespace_survives_restart(store):
    item = accounts.create({"platform": "vk", "login": " user ", "password": "  pw  "})
    assert item["password"] == "  pw  " and item["login"] == "user"
    accounts.update(item["id"], {"password": " new secret "})
    accounts._items = None
    assert accounts.get(item["id"])["password"] == " new secret "


@pytest.mark.parametrize("sep", [":", ";", ",", "\t"])
def test_import_preserves_password_whitespace(store, sep):
    report = accounts.import_report(f" user{sep}  pw  \nother{sep}  p2  {sep} host ", "vk")
    assert [a["password"] for a in report["created"]] == ["  pw  ", "  p2  "]
    assert [a["login"] for a in report["created"]] == ["user", "other"]
    assert report["created"][1]["proxy"] == "host"


def test_api_save_failure_is_503_without_secret(store, monkeypatch):
    from farm import server
    from test_request_limits import invoke
    monkeypatch.delenv("FARM_TOKEN", raising=False)

    def fail(*args):
        raise OSError("disk full TOPSECRET")

    monkeypatch.setattr(accounts.os, "replace", fail)
    payload = json.dumps({"platform": "vk", "login": "new", "password": "TOPSECRET"}).encode()
    status, _, body = asyncio.run(invoke(server.create_app(), path="/api/accounts", chunks=[payload],
                                        headers=[(b"content-type", b"application/json")]))
    assert status == 503
    assert b"TOPSECRET" not in body
    assert accounts.all_accounts() == []
