"""Итог массового действия по каждому телефону: причина сбоя кодом,
выпавшие из сети не теряются, разброс не прячет итог за «запланировано»."""
import threading
from types import SimpleNamespace

from farm.api import bulk


def test_причины_adb_кодами():
    cases = {
        "adb -s X shell input -> rc=1: error: device offline": "offline",
        "adb -s X reboot -> rc=1: error: device 'X' not found": "not_found",
        "adb -s X shell -> rc=1: error: device unauthorized.": "unauthorized",
        "adb таймаут: -s X install -r -g /tmp/a.apk": "timeout",
        "adb: failed to install a.apk: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]": "no_space",
        "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package x signatures do not match]": "signature",
        "Failure [INSTALL_FAILED_OLDER_SDK]": "old_android",
        "Failure [INSTALL_FAILED_NO_MATCHING_ABIS: ...]": "abi",
        "Failure [INSTALL_FAILED_DUPLICATE_PERMISSION]": "install_other",
        "что-то совсем другое": "other",
    }
    for msg, reason in cases.items():
        assert bulk.failure(msg)["reason"] == reason, msg
    assert bulk.failure("Failure [INSTALL_FAILED_OLDER_SDK]")["code"] == "INSTALL_FAILED_OLDER_SDK"


def test_длинная_ошибка_сохраняет_хвост():
    msg = "adb -s X install -r -g /tmp/" + "x" * 400 + ".apk -> rc=1: Failure [INSTALL_FAILED_OLDER_SDK]"
    f = bulk.failure(msg)
    assert f["error"].endswith("[INSTALL_FAILED_OLDER_SDK]") and len(f["error"]) < 320


def _registry(monkeypatch, online):
    monkeypatch.setattr(bulk.registry, "get", lambda s: SimpleNamespace(online=s in online))


def _fresh_queues(monkeypatch):
    monkeypatch.setattr(bulk, "_queues", {})
    monkeypatch.setattr(bulk, "_last_due", {})
    monkeypatch.setattr(bulk, "_sleeping", {})


def test_без_разброса_выпавшие_из_сети_в_итоге(monkeypatch):
    _registry(monkeypatch, {"a", "b"})
    monkeypatch.setitem(bulk.ACTIONS, "probe", lambda s, p: None)
    res = bulk.bulk_action(["a", "b", "c"], {"type": "probe"}, None, None)
    assert (res["done"], res["failed"]) == (2, 1)
    assert res["results"]["c"]["reason"] == "offline"


def test_с_разбросом_ждём_итог(monkeypatch):
    _registry(monkeypatch, {"a", "b"})
    _fresh_queues(monkeypatch)

    def probe(s, p):
        if s == "b":
            raise RuntimeError("error: device offline")

    monkeypatch.setitem(bulk.ACTIONS, "probe", probe)
    res = bulk.bulk_action(["a", "b"], {"type": "probe"}, [0, 0.05], None)
    assert "queued" not in res
    assert (res["done"], res["failed"]) == (1, 1)
    assert res["results"]["b"]["reason"] == "offline"


def test_аварийная_остановка_отменяет_ожидание(monkeypatch):
    _registry(monkeypatch, {"a"})
    _fresh_queues(monkeypatch)
    monkeypatch.setitem(bulk.ACTIONS, "probe", lambda s, p: None)
    out = {}
    th = threading.Thread(target=lambda: out.update(
        bulk.bulk_action(["a"], {"type": "probe"}, [3, 3], None)))
    th.start()
    for _ in range(200):
        if bulk._sleeping.get("a"):   # очередь достала жест и ждёт срока
            break
        threading.Event().wait(0.01)
    assert bulk.drain_queues() == 1
    th.join(5)
    assert out["results"]["a"]["reason"] == "stopped"
