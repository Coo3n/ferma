"""/api/run принимает метку запуска: пробный запуск и остальные — один запуск."""
import pytest
from fastapi import HTTPException

from farm.api import scenarios as api


class _Job:
    def __init__(self, batch):
        self.batch = batch

    def to_dict(self):
        return {"batch": self.batch}


@pytest.fixture
def seen(monkeypatch):
    got = {}

    def submit(key, serials, params, repeat, **kw):
        got.update(kw, key=key, serials=serials)
        return [_Job(kw.get("batch") or "fresh00000")]

    monkeypatch.setattr(api.runner, "submit", submit)
    return got


def test_без_метки_запуск_новый(seen):
    res = api.run_scenario({"scenario": "a", "serials": ["s1"]})
    assert seen["batch"] is None
    assert res["batch"] == "fresh00000"


def test_метка_передаётся_в_очередь(seen):
    res = api.run_scenario({"scenario": "a", "serials": ["s2", "s3"], "batch": "abc123def0"})
    assert seen["batch"] == "abc123def0"
    assert res["batch"] == "abc123def0"


@pytest.mark.parametrize("bad", ["../x", "ABC123DEF0", "a" * 40, "12", 123, ["abc123"]])
def test_чужая_метка_отклоняется(seen, bad):
    with pytest.raises(HTTPException) as e:
        api.run_scenario({"scenario": "a", "serials": ["s1"], "batch": bad})
    assert e.value.status_code == 400
    assert not seen
