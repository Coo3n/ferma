"""GET /api/scenarios: структура и здоровье в карточке."""
import json

import pytest

from farm import config, guards, scenarios
from farm.api import scenarios as api
from farm.devices.runner import FAILED, PASSED, Job
from farm.devices.runner import runner as глобальный_runner
from farm.recorder import save, steps


@pytest.fixture
def песочница(tmp_path, monkeypatch):
    scen, grd, art = tmp_path / "scenarios", tmp_path / "guards", tmp_path / "artifacts"
    scen.mkdir(), grd.mkdir(), art.mkdir()
    monkeypatch.setattr(config, "SCENARIOS_DIR", scen)
    monkeypatch.setattr(config, "GUARDS_DIR", grd)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", art)
    scenarios._cache.clear()
    guards._cache.clear()
    yield scen, grd, art
    # чужие Job из других тестов, использующих тот же глобальный runner, не
    # трогаем — но свои подчищаем, чтобы не текли между тестами файла
    for jid in list(глобальный_runner.jobs):
        if глобальный_runner.jobs[jid].scenario_key.startswith("test_"):
            глобальный_runner.jobs.pop(jid, None)
            try:
                глобальный_runner.order.remove(jid)
            except ValueError:
                pass


def _recorded(key: str, params: dict) -> None:
    meta = {"name": key, "description": "", "watch_popups": False}
    шаги = [
        steps.normalize_step({"kind": "unlock", "args": {}}),
        steps.normalize_step({
            "kind": "branch",
            "args": {"name": "экран"},
            "arms": [{"name": "ветка", "any": ['text="метка"'], "run": ""}],
        }),
    ]
    save.save(key, meta, params, шаги)


def test_голый_py_без_рецепта_не_даёт_структуру(песочница):
    scen, _, _ = песочница
    (scen / "test_руками.py").write_text(
        "NAME = 'Руками'\n\ndef run(ctx):\n    pass\n", "utf-8")

    item = next(i for i in api.list_scenarios() if i["key"] == "test_руками")
    assert item["editable"] is False
    assert item["steps"] is None
    assert item["branches"] is None


def test_записанный_сценарий_даёт_шаги_и_развилки(песочница):
    _recorded("test_demo", {})

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["editable"] is True
    assert item["steps"] == 2
    assert item["branches"] == 1


def test_без_пакета_в_параметрах_преграды_не_считаются(песочница):
    _recorded("test_demo", {})

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["uncovered"] is None


def test_пакет_из_параметра_считает_непокрытые_преграды(песочница):
    scen, grd, art = песочница
    _recorded("test_demo", {"package": {"label": "Пакет", "default": "com.app"}})

    job_dir = art / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(json.dumps({
        "package": "com.app", "texts": ["Тариф"],
        "candidates": [{"selector": {"text": "Тариф"}}],
    }), "utf-8")

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["uncovered"] == 1


def test_отвод_закрывает_преграду(песочница):
    scen, grd, art = песочница
    _recorded("test_demo", {"package": {"label": "Пакет", "default": "com.app"}})

    job_dir = art / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(json.dumps({
        "package": "com.app", "texts": ["Тариф"],
        "candidates": [{"selector": {"text": "Тариф"}}],
    }), "utf-8")
    (grd / "com.app.json").write_text(json.dumps([
        {"name": "закрыть", "when": {"any": [{"text": "Тариф"}]}, "action": {"run": "test_demo"}},
    ]), "utf-8")
    guards._cache.clear()

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["uncovered"] == 0


def test_прогоны_считаются_по_ключу_сценария(песочница):
    _recorded("test_demo", {})
    for status in (PASSED, PASSED, FAILED):
        j = Job(id=f"test_demo-{status}-{len(глобальный_runner.jobs)}",
                scenario_key="test_demo", scenario_name="test_demo",
                serial="dev1", device_name="dev1", params={}, status=status)
        глобальный_runner.jobs[j.id] = j
        глобальный_runner.order.append(j.id)

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["passed"] == 2
    assert item["failed"] == 1
