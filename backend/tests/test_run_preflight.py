"""Проверка перед запуском: какие аккаунты нужны сценарию и готов ли телефон."""
import types

from farm import accounts, scenarios
from farm.devices import runner


def test_needs_accounts_literals_only():
    src = ('def run(ctx):\n    ctx.account("vk")\n    ctx.account("tg")["login"]\n'
           '    ctx.account(p)\n    ctx.account("fb")\n')
    assert scenarios.needs_accounts(src) == ["tg", "vk"]


def test_needs_accounts_none():
    assert scenarios.needs_accounts("def run(ctx):\n    pass\n") == []


def test_needs_accounts_broken_source():
    assert scenarios.needs_accounts("def run(:") == []


def _dev(serial, online=True, busy=None):
    return types.SimpleNamespace(serial=serial, online=online, busy_job=busy)


def test_preflight_statuses(monkeypatch):
    devs = {"a": _dev("a"), "b": _dev("b", online=False), "c": _dev("c", busy="j"),
            "d": _dev("d"), "e": _dev("e"), "f": _dev("f")}
    monkeypatch.setattr(scenarios.registry, "get", devs.get)
    accs = {"a": {"status": "active"}, "c": {"status": "active"},
            "e": {"status": "banned"}, "f": {"status": "login"}}
    monkeypatch.setattr(accounts, "for_device", lambda s, p=None: accs.get(s))
    out = scenarios.preflight(types.SimpleNamespace(needs_accounts=["vk"]), list(devs) + ["zz"])
    st = {k: v["status"] for k, v in out["devices"].items()}
    assert st == {"a": "ready", "b": "offline", "c": "busy", "d": "no_account",
                  "e": "banned", "f": "login", "zz": "offline"}
    assert out["devices"]["d"]["platform"] == "vk"
    assert out["counts"] == {"ready": 1, "offline": 2, "busy": 1, "no_account": 1,
                             "banned": 1, "login": 1}


def test_preflight_without_accounts_needed(monkeypatch):
    monkeypatch.setattr(scenarios.registry, "get", lambda s: _dev(s))
    out = scenarios.preflight(types.SimpleNamespace(needs_accounts=[]), ["x"])
    assert out["devices"]["x"]["status"] == "ready"


def test_summary_hides_credentials(monkeypatch):
    monkeypatch.setattr(accounts, "_items", [
        {"id": "1", "platform": "vk", "login": "L", "password": "P", "serial": "s", "status": "banned"},
        {"id": "2", "platform": "tg", "login": "L2", "password": "P2", "serial": "x", "status": "new"},
    ])
    assert accounts.summary_for("s") == [{"platform": "vk", "status": "banned"}]


def test_submit_shares_one_batch(monkeypatch):
    sc = types.SimpleNamespace(key="k", name="K", error="", params={})
    monkeypatch.setattr(runner.scenarios, "get", lambda key: sc)
    monkeypatch.setattr(runner.scenarios, "resolve_params", lambda s, p: {})
    monkeypatch.setattr(runner.registry, "get", lambda s: types.SimpleNamespace(name=s))
    r = runner.Runner()
    queued = []
    r._queue_for = lambda serial: types.SimpleNamespace(put=queued.append)
    first = r.submit("k", ["a", "b"], repeat=2)
    second = r.submit("k", ["a"])
    assert len({j.batch for j in first}) == 1 and first[0].batch
    assert second[0].batch != first[0].batch
