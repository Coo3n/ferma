"""Действия смены разрешения и чтение текущего размера с телефонов."""
import pytest

from farm.api import bulk, screen


@pytest.fixture
def shell(monkeypatch):
    calls = []
    monkeypatch.setattr(screen.adb, "shell",
                        lambda serial, cmd, timeout=None: calls.append((serial, cmd)) or "")
    forgot = []
    monkeypatch.setattr(screen.control, "forget_size", lambda serial: forgot.append(serial))
    return calls, forgot


def test_resolution_set_runs_wm_and_forgets_cached_size(shell):
    calls, forgot = shell
    screen.ACTIONS["resolution_set"]("S1", {"type": "resolution_set", "width": 720,
                                            "height": 1600, "density": 320})
    assert calls == [("S1", "wm size 720x1600"), ("S1", "wm density 320")]
    assert forgot == ["S1"]


def test_resolution_set_without_density_skips_it(shell):
    calls, _ = shell
    screen.ACTIONS["resolution_set"]("S1", {"width": 720, "height": 1600, "density": ""})
    assert calls == [("S1", "wm size 720x1600")]


def test_resolution_set_rejects_bad_values_before_touching_the_phone(shell):
    calls, _ = shell
    with pytest.raises(ValueError):
        screen.ACTIONS["resolution_set"]("S1", {"width": 50, "height": 1600})
    with pytest.raises(ValueError):
        screen.ACTIONS["resolution_set"]("S1", {})
    assert calls == []


def test_resolution_reset(shell):
    calls, forgot = shell
    screen.ACTIONS["resolution_reset"]("S1", {"type": "resolution_reset"})
    assert calls == [("S1", "wm size reset"), ("S1", "wm density reset")]
    assert forgot == ["S1"]


def test_bulk_uses_same_table():
    assert "resolution_set" in bulk.ACTIONS and bulk.ACTIONS is screen.ACTIONS


def test_display_info_reads_size_and_density(monkeypatch):
    answers = {
        "wm size": "Physical size: 1080x2400\nOverride size: 720x1600\n",
        "wm density": "Physical density: 420\nOverride density: 320\n",
    }
    monkeypatch.setattr(bulk.adb, "shell", lambda serial, cmd, timeout=None: answers[cmd])
    assert bulk._display_info("S1") == {
        "size": [720, 1600], "physical": [1080, 2400], "overridden": True,
        "density": 320, "physical_density": 420}


def test_display_info_not_overridden(monkeypatch):
    answers = {"wm size": "Physical size: 1080x2400\n", "wm density": "Physical density: 420\n"}
    monkeypatch.setattr(bulk.adb, "shell", lambda serial, cmd, timeout=None: answers[cmd])
    got = bulk._display_info("S1")
    assert got["overridden"] is False and got["size"] == [1080, 2400]


def test_bulk_display_endpoint_summarises_each_phone(monkeypatch):
    monkeypatch.setattr(bulk, "_online", lambda serials: list(serials))
    monkeypatch.setattr(bulk, "_display_info", lambda s: {"size": [1080, 2400]})
    got = bulk.bulk_display(serials=["A", "B"])
    assert got["done"] == 2 and got["results"]["A"]["size"] == [1080, 2400]
