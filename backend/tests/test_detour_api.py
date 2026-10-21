"""Создание отвода: записанные шаги → блок + страж. Устройство не нужно."""
import json

import pytest
from fastapi import HTTPException

from farm import config, guards, scenarios
from farm.api import detours as api


@pytest.fixture
def песочница(tmp_path, monkeypatch):
    scen, grd = tmp_path / "scenarios", tmp_path / "guards"
    scen.mkdir(), grd.mkdir()
    monkeypatch.setattr(config, "SCENARIOS_DIR", scen)
    monkeypatch.setattr(config, "GUARDS_DIR", grd)
    scenarios._cache.clear()
    guards._cache.clear()
    return scen, grd


ТЕЛО = {
    "key": "close_tariff",
    "name": "Закрыть тариф",
    "package": "com.app",
    "when": {"textContains": "Выберите тариф"},
    "steps": [{"kind": "click", "args": {},
               "selector": {"call": "click", "args": 'text="Позже"'}}],
}


def test_отвод_создаёт_блок_и_стража(песочница):
    scen, grd = песочница
    api.create_detour(dict(ТЕЛО))

    assert 'ctx.click(text="Позже")' in (scen / "close_tariff.py").read_text("utf-8")
    правила = json.loads((grd / "com.app.json").read_text("utf-8"))
    assert правила[0]["action"] == {"run": "close_tariff"}
    assert правила[0]["when"]["any"] == [{"textContains": "Выберите тариф"}]


def test_страж_годен_для_движка(песочница):
    """Записанное правило обязано грузиться движком, а не только лежать в файле."""
    api.create_detour(dict(ТЕЛО))
    имена = [g.name for g in guards.load("com.app")]
    assert "close_tariff" in имена


def test_второй_отвод_дописывается_а_не_затирает(песочница):
    _, grd = песочница
    api.create_detour(dict(ТЕЛО))
    api.create_detour(dict(ТЕЛО, key="skip_ad", name="Закрыть рекламу",
                           when={"textContains": "Реклама"}))
    правила = json.loads((grd / "com.app.json").read_text("utf-8"))
    assert len(правила) == 2


def test_повторное_имя_отвергается(песочница):
    api.create_detour(dict(ТЕЛО))
    with pytest.raises(HTTPException) as e:
        api.create_detour(dict(ТЕЛО))
    assert e.value.status_code == 409


def test_без_условия_нельзя(песочница):
    with pytest.raises(HTTPException) as e:
        api.create_detour(dict(ТЕЛО, when={}))
    assert e.value.status_code == 400


def test_без_шагов_нельзя(песочница):
    with pytest.raises(HTTPException) as e:
        api.create_detour(dict(ТЕЛО, steps=[]))
    assert e.value.status_code == 400


def test_без_пакета_пишется_в_глобальные(песочница):
    _, grd = песочница
    api.create_detour(dict(ТЕЛО, package=""))
    assert (grd / "global.json").exists()


def test_кривой_пакет_отвергается(песочница):
    """Пакет идёт в имя файла — путь наружу недопустим."""
    with pytest.raises(HTTPException) as e:
        api.create_detour(dict(ТЕЛО, package="../побег"))
    assert e.value.status_code == 400


# ------------------------------------------------------------ карта отводов

@pytest.fixture
def с_артефактами(песочница, tmp_path, monkeypatch):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    monkeypatch.setattr(config, "ARTIFACTS_DIR", arts)
    return песочница + (arts,)


def падение(arts, job, rid, text, package="com.app"):
    d = arts / job
    d.mkdir()
    (d / "obstacle.json").write_text(json.dumps({
        "package": package, "texts": [text],
        "candidates": [{"selector": {"resourceId": rid}, "label": f"по id: {rid}"}],
    }, ensure_ascii=False), "utf-8")


def test_карта_показывает_непокрытые_преграды(с_артефактами):
    *_, arts = с_артефактами
    падение(arts, "job1", "com.app:id/tariff", "Выберите тариф")
    падение(arts, "job2", "com.app:id/tariff", "Выберите тариф")
    падение(arts, "job3", "com.app:id/ad", "Реклама")

    карта = api.detour_map(package="com.app")
    дыры = {o["texts"][0]: o["hits"] for o in карта["obstacles"]}
    assert дыры == {"Выберите тариф": 2, "Реклама": 1}
    assert карта["obstacles"][0]["texts"] == ["Выберите тариф"], "частое — первым"


def test_после_обучения_преграда_уходит_с_карты(с_артефактами):
    *_, arts = с_артефактами
    падение(arts, "job1", "com.app:id/tariff", "Выберите тариф")
    падение(arts, "job2", "com.app:id/ad", "Реклама")

    api.create_detour(dict(ТЕЛО, when={"resourceId": "com.app:id/tariff"}))

    карта = api.detour_map(package="com.app")
    assert [o["texts"][0] for o in карта["obstacles"]] == ["Реклама"]
    assert any(r["action"].get("run") == "close_tariff" for r in карта["rules"])


def test_карта_не_мешает_чужие_приложения(с_артефактами):
    *_, arts = с_артефактами
    падение(arts, "job1", "com.other:id/x", "Чужое", package="com.other")
    assert api.detour_map(package="com.app")["obstacles"] == []


def test_преграда_помнит_задачу_для_обучения(с_артефактами):
    """Кнопка «научить» на схеме ведёт в задачу — без её id она мертва."""
    *_, arts = с_артефактами
    падение(arts, "job42", "com.app:id/tariff", "Выберите тариф")
    карта = api.detour_map(package="com.app")
    assert карта["obstacles"][0]["job"] == "job42"


def test_scan_obstacles_читает_слепки_из_артефактов(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(
        json.dumps({"package": "com.app", "texts": ["Тариф"],
                    "candidates": [{"selector": {"text": "Тариф"}}]}),
        "utf-8")

    слепки = scan_obstacles("com.app")
    assert len(слепки) == 1
    assert слепки[0]["job"] == "job1"
    assert слепки[0]["file"] == "obstacle.json"


def test_scan_obstacles_фильтрует_по_пакету(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(
        json.dumps({"package": "com.other", "texts": [], "candidates": []}),
        "utf-8")

    assert scan_obstacles("com.app") == []


def test_scan_obstacles_без_пакета_не_фильтрует(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(
        json.dumps({"package": "com.other", "texts": [], "candidates": []}),
        "utf-8")

    assert len(scan_obstacles("")) == 1


def test_scan_obstacles_без_папки_артефактов_не_падает(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "нет-такой-папки")
    assert scan_obstacles("com.app") == []


def test_правило_без_обучения_добавляется_и_удаляется(песочница):
    _, grd = песочница
    r = api.add_rule({"package": "com.app", "name": "Не сейчас",
                      "when": [{"text": "Не сейчас"}], "action": {"click": {"text": "Не сейчас"}}})
    assert r["name"] == "Не сейчас"
    # одноимённое — с номером, а не затирает первое
    r2 = api.add_rule({"package": "com.app", "name": "Не сейчас",
                       "when": [{"text": "Позже"}], "action": {"key": "back"}})
    assert r2["name"] == "Не сейчас (2)"
    names = [g.name for g in guards.load("com.app")]
    assert names == ["Не сейчас", "Не сейчас (2)"]
    api.delete_rule("Не сейчас", "com.app")
    assert [g.name for g in guards.load("com.app")] == ["Не сейчас (2)"]


def test_правило_для_всех_приложений_и_проверка(песочница):
    _, grd = песочница
    api.add_rule({"package": "", "name": "Разрешить", "when": [{"text": "Разрешить"}],
                  "action": {"click": {"text": "Разрешить"}}})
    assert (grd / "global.json").exists()
    with pytest.raises(HTTPException):
        api.add_rule({"package": "com.app", "when": [], "action": {"key": "back"}})
    with pytest.raises(HTTPException):
        api.add_rule({"package": "com.app", "when": [{"text": "x"}], "action": {"run": "Bad Key"}})
    with pytest.raises(HTTPException):
        api.delete_rule("нет такого", "com.app")


def test_правило_правится_и_переносится(песочница):
    _, grd = песочница
    api.add_rule({"package": "com.app", "name": "Окно", "when": [{"text": "Позже"}],
                  "action": {"click": {"text": "Позже"}}, "img": "data:image/png;base64,AAA"})
    api.edit_rule({"package": "com.app", "name": "Окно", "action": {"key": "back"}})
    g = guards.load("com.app")[0]
    assert g.action == {"key": "back"}
    # картинка правила сохранилась при правке
    assert api.detour_map("com.app")["rules"][0]["img"] == "data:image/png;base64,AAA"
    api.edit_rule({"package": "com.app", "name": "Окно", "to_package": ""})
    assert [x.name for x in guards.load("")] == ["Окно"]
    assert not json.loads((grd / "com.app.json").read_text("utf-8"))


def test_правила_выключаются_для_сценария(песочница, monkeypatch):
    monkeypatch.setattr(api.saver, "load_recipe", lambda key: {"steps": [
        {"kind": "launch_app", "args": {"package": "com.app"}}]})
    api.add_rule({"package": "com.app", "name": "A", "when": [{"text": "A"}], "action": {"key": "back"}})
    info = api.scenario_rules("my_scen")
    assert info["packages"] == ["com.app"] and [r["name"] for r in info["rules"]] == ["A"]
    assert info["off"] is False
    api.scenario_rules_toggle("my_scen", {"off": True})
    assert api.scenario_rules("my_scen")["off"] is True
    assert "my_scen" in guards.scenarios_off()


def test_выключенные_правила_не_пробуются_в_запуске(песочница):
    from types import SimpleNamespace
    from farm.context import DeviceContext

    class Engine:
        calls = 0

        def try_all(self, ctx):
            Engine.calls += 1
            return ["x"]

    fake = SimpleNamespace(scenario_key="s1", _guards=Engine(), log=lambda *a: None)
    assert DeviceContext._rescue(fake) is True
    guards.set_scenario_off("s1", True)
    assert DeviceContext._rescue(fake) is False
    assert Engine.calls == 1


def test_не_помеха_убирается_из_списка(песочница, monkeypatch):
    monkeypatch.setattr(api, "scan_obstacles", lambda package="": [
        {"job": "j1", "file": "obstacle.json", "texts": ["Главная"], "package": "com.app", "candidates": []}])
    monkeypatch.setattr(api.obstacle, "uncovered", lambda found, rules: found)
    assert len(api.detour_map("com.app")["obstacles"]) == 1
    api.ignore_obstacle({"job": "j1", "file": "obstacle.json"})
    assert api.detour_map("com.app")["obstacles"] == []
