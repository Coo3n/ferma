"""Засев демо починки: артефакты валидны, дамп парсится, отклонения записаны.
Сервер и порты не нужны."""
import importlib.util
import json
from pathlib import Path

import pytest

from farm import config, deviations as dv, scenarios
from farm.api import deviations as api_dev

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "seed_repair_demo.py"


@pytest.fixture
def мир(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(scenarios, "_cache", {})
    dv.deviations.clear()
    yield tmp_path
    dv.deviations.clear()


def _load():
    spec = importlib.util.spec_from_file_location("seed_repair_demo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_builds_valid_artifacts(мир):
    info = _load().seed(мир)
    assert info["nodes"] >= 4
    payload = api_dev.deviation_dump(info["ids"]["repair"])
    assert payload["nodes"] and payload["screenshot"].startswith("data:image/jpeg")
    assert (payload["width"], payload["height"]) == (1080, 2400)
    recipe = json.loads(Path(info["recipe"]).read_text("utf-8"))
    assert recipe["steps"][1]["kind"] == "click" and recipe["steps"][1]["texts"] == ["Войти"]
    assert "click_target" in Path(info["scenario_file"]).read_text("utf-8")
    items = {i["id"]: i for i in dv.deviations.list()}
    assert [items[info["ids"][k]]["step_index"] for k in ("repair", "manual", "gone")] == [1, -1, 1]
    assert (мир / "scenarios" / "demo_manual.py").exists()
    assert not (мир / "scenarios" / "demo_manual_assets").exists()   # рецепта нет


def test_seed_refuses_real_directories(мир, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", config.ROOT / "scenarios")
    with pytest.raises(RuntimeError):
        _load().seed(мир)
