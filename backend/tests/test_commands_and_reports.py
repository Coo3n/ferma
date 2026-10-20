"""Команды (короткие записи) и отчёт запуска по шагам."""
import json

from farm import config
from farm.api import jobs as jobs_api
from farm.recorder import validate as rv


def _payload(n, command):
    steps = [{"kind": "sleep", "args": {"seconds": 1}} for _ in range(n)]
    return {"meta": {"name": "x", "command": command}, "params": {}, "steps": steps}


def test_команда_длиннее_лимита_не_проходит():
    res = rv.validate(_payload(rv.COMMAND_MAX_STEPS + 1, True))
    assert any("команда" in e["text"] for e in res["errors"])


def test_сценарий_того_же_размера_проходит():
    res = rv.validate(_payload(rv.COMMAND_MAX_STEPS + 1, False))
    assert not any("команда" in e["text"] for e in res["errors"])


def test_таблица_по_шагам_строка_на_шаг(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "abc123").mkdir()
    (tmp_path / "abc123" / "report.json").write_text(json.dumps({"steps": [
        {"i": 0, "label": "Открыть", "status": "ok", "secs": 1.0},
        {"i": 1, "label": "Нажать «Ок»", "status": "failed", "secs": 2.5, "shot": "99_failure.jpg"},
    ]}), "utf-8")
    out = jobs_api.steps_csv([{"id": "abc123", "scenario_name": "S", "device_name": "P",
                               "status": "failed", "error": "нет кнопки", "created_at": 1}], "http://h")
    lines = out.strip().split("\r\n")
    assert len(lines) == 3
    assert "упал" in lines[2] and "HYPERLINK" in lines[2] and "нет кнопки" in lines[2]
    assert "HYPERLINK" not in lines[1]
