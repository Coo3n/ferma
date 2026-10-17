"""Прогон одного шага: module_from_step(start, stop) оставляет только его
и строки без номера шага (подготовка вроде watch_popups)."""
import types

import pytest

from farm import stepflow

SRC = "def run(ctx):\n    ctx.prep()\n    ctx.s0()\n    ctx.s1()\n    ctx.s2()\n"
LINE_MAP = {3: 0, 4: 1, 5: 2}


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda: self.calls.append(name)


def _run(tmp_path, start, stop=None):
    path = tmp_path / "sc.py"
    path.write_text(SRC)
    sc = types.SimpleNamespace(path=str(path), module=types.ModuleType("sc"))
    ctx = Recorder()
    stepflow.module_from_step(sc, LINE_MAP, start, stop).run(ctx)
    return ctx.calls


def test_only_one_step_keeps_preamble(tmp_path):
    assert _run(tmp_path, 1, 2) == ["prep", "s1"]


def test_first_step_alone(tmp_path):
    assert _run(tmp_path, 0, 1) == ["prep", "s0"]


def test_from_step_without_stop_runs_to_end(tmp_path):
    assert _run(tmp_path, 1) == ["prep", "s1", "s2"]


def test_start_beyond_scenario_rejected(tmp_path):
    with pytest.raises(ValueError):
        _run(tmp_path, 5, 6)
