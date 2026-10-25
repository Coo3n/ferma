"""Лестница повторов dump_hierarchy и лечение зависшего uiautomator."""
import pytest

from farm.control import diagnostics as dg
from farm.devices import pool


def _flaky(*errors, result="<xml/>"):
    queue = list(errors)

    def fetch():
        if queue:
            raise queue.pop(0)
        return result
    return fetch


def _run(fetch, **kw):
    sleeps, heals = [], []
    kw.setdefault("delays", (1, 2, 3, 5))
    kw.setdefault("recover_after", 2)
    try:
        out = dg.fetch_with_retry(fetch, lambda: heals.append(1), sleep=sleeps.append, **kw)
    except Exception as e:  # noqa: BLE001
        out = e
    return out, sleeps, len(heals)


def test_success_first_try():
    assert _run(_flaky()) == ("<xml/>", [], 0)


def test_ladder_then_success_without_recovery():
    out, sleeps, heals = _run(_flaky(RuntimeError("x")))
    assert out == "<xml/>" and sleeps == [1] and heals == 0


def test_recovery_after_n_failures():
    out, sleeps, heals = _run(_flaky(RuntimeError("a"), RuntimeError("b")))
    assert out == "<xml/>" and sleeps == [1] and heals == 1


def test_ladder_exhausted_raises_last():
    out, sleeps, heals = _run(_flaky(*[RuntimeError(str(i)) for i in range(20)]))
    assert isinstance(out, RuntimeError) and sleeps == [1, 2, 3, 5] and heals == 1


def test_timeout_gets_exactly_one_retry_after_recovery():
    out, sleeps, heals = _run(_flaky(TimeoutError("t")))
    assert out == "<xml/>" and sleeps == [] and heals == 1
    out, sleeps, heals = _run(_flaky(TimeoutError("t"), TimeoutError("t2")))
    assert isinstance(out, TimeoutError) and sleeps == [] and heals == 1


def test_dead_service_recovers_immediately():
    out, sleeps, heals = _run(_flaky(RuntimeError("UiAutomation not connected")))
    assert out == "<xml/>" and sleeps == [] and heals == 1


def test_note_called_on_recovery():
    notes = []
    dg.fetch_with_retry(_flaky(TimeoutError("t")), lambda: None,
                        sleep=lambda s: None, note=notes.append)
    assert len(notes) == 1


def test_dump_hierarchy_wires_pool_and_counts(monkeypatch):
    class Dev:
        n = 0
        reset = 0

        def dump_hierarchy(self):
            Dev.n += 1
            if Dev.n == 1:
                raise TimeoutError("hang")
            return "<ok/>"

        def reset_uiautomator(self):
            Dev.reset += 1

    dev = Dev()
    monkeypatch.setattr(pool, "_clients", {"s9": dev})
    monkeypatch.setattr(pool, "_recoveries", {})
    # после drop клиент поднимается заново — подсовываем того же
    monkeypatch.setattr(pool, "get", lambda serial, force=False: dev)
    lines = []
    dg.bind_log("s9", lines.append)
    try:
        assert dg.dump_hierarchy("s9") == "<ok/>"
    finally:
        dg.bind_log("s9", None)
    assert dg.recoveries("s9") == 1 and Dev.reset == 1
    assert len(lines) == 1 and "uiautomator" in lines[0]
