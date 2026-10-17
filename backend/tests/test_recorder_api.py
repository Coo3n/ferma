"""Коды ответов конструктора. TestClient недоступен — зовём функции роутера."""
import pytest
from fastapi import HTTPException

from farm import config, scenarios
from farm.api import recorder as api_recorder
from farm.api import scenarios as api_scenarios

META = {"name": "Тест", "watch_popups": False}
STEPS = [{"kind": "unlock", "args": {}}]


@pytest.fixture
def scen_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    return tmp_path


def test_предпросмотр_возвращает_исходник():
    text = api_recorder.preview({"meta": META, "params": {}, "steps": STEPS})
    assert "def run(ctx):" in text
    assert "ctx.unlock()" in text


def test_кривой_шаг_даёт_400():
    with pytest.raises(HTTPException) as e:
        api_recorder.preview({"meta": META, "steps": [{"kind": "танцевать"}]})
    assert e.value.status_code == 400


def test_необъявленный_параметр_даёт_400():
    with pytest.raises(HTTPException) as e:
        api_recorder.preview({
            "meta": META, "params": {},
            "steps": [{"kind": "type", "args": {"value": "x"}, "param": "login"}],
        })
    assert e.value.status_code == 400


def test_сохранение_создаёт_файл_и_он_виден_в_списке(scen_dir):
    result = api_recorder.save_scenario(
        {"key": "flow_ok", "meta": META, "steps": STEPS})
    assert result["key"] == "flow_ok"
    assert (scen_dir / "flow_ok.py").exists()
    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["flow_ok"].recorded is True


def test_кириллический_ключ_даёт_400(scen_dir):
    with pytest.raises(HTTPException) as e:
        api_recorder.save_scenario({"key": "поток", "meta": META, "steps": STEPS})
    assert e.value.status_code == 400


def test_коллизия_даёт_409(scen_dir):
    api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    with pytest.raises(HTTPException) as e:
        api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    assert e.value.status_code == 409


def test_перезапись_проходит(scen_dir):
    api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    result = api_recorder.save_scenario(
        {"key": "flow", "meta": META, "steps": STEPS, "overwrite": True})
    assert result["key"] == "flow"


def test_записанный_сценарий_удаляется(scen_dir):
    api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    assert api_scenarios.delete_scenario("flow") == {"ok": True}
    assert not (scen_dir / "flow.py").exists()


def test_ручной_сценарий_удалить_нельзя(scen_dir):
    (scen_dir / "ручной.py").write_text("def run(ctx):\n    pass\n", "utf-8")
    with pytest.raises(HTTPException) as e:
        api_scenarios.delete_scenario("ручной")
    assert e.value.status_code == 403


def test_удаление_отсутствующего_даёт_404(scen_dir):
    with pytest.raises(HTTPException) as e:
        api_scenarios.delete_scenario("нету")
    assert e.value.status_code == 404


# ---------------------------------------------------------------- фронтенд
# Тело запроса ровно той формы, какую собирает recPayload() в
# frontend/js/recorder.js. JS-тестов в проекте нет, поэтому расхождение фронта
# с бэком ловится отсюда: поменяется контракт — тест покраснеет.
PAYLOAD_ОТ_ФРОНТА = {
    "key": "flow_layers",
    "meta": {"name": "Запись со слоями", "watch_popups": False},
    "params": {},
    "steps": [
        {
            "kind": "click",
            "args": {},
            "selector": {"call": "click", "args": 'resourceId="com.app:id/login"',
                         "fallbacks": ['description="Войти"']},
            "param": None,
            "note": "Войти",
            "texts": ["Войти", "Log in"],
            "point": [0.5213, 0.8107],
            "crop": "01_click.png",
        },
    ],
    # base64 однопиксельного png — ровно то, что отдаёт canvas.toDataURL
    "assets": {"01_click.png": (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")},
    "screen_width": 1080,
}


def test_запись_со_слоями_сохраняется_целиком(scen_dir):
    """Сквозная проверка: фронт прислал слои — на диске сценарий и кроп."""
    api_recorder.save_scenario(dict(PAYLOAD_ОТ_ФРОНТА))

    код = (scen_dir / "flow_layers.py").read_text("utf-8")
    assert "ctx.click_target(" in код
    assert 'text=["Войти", "Log in"]' in код
    assert 'img="01_click.png"' in код
    assert "at=(0.521, 0.811)" in код

    ассеты = scen_dir / "flow_layers_assets"
    assert (ассеты / "01_click.png").read_bytes().startswith(b"\x89PNG")
    import json
    assert json.loads((ассеты / "meta.json").read_text("utf-8")) == {"screen_width": 1080}


def test_предпросмотр_слоёв_совпадает_с_сохранением():
    """«⟨⟩ код» обязан показывать то же, что ляжет в файл."""
    тело = {k: v for k, v in PAYLOAD_ОТ_ФРОНТА.items() if k != "key"}
    assert "ctx.click_target(" in api_recorder.preview(тело)


def test_якорь_экрана_от_фронта_сохраняется(scen_dir):
    """Шаг expect в той форме, какую собирает recMaybeAnchor() в recorder.js."""
    api_recorder.save_scenario({
        "key": "flow_anchor",
        "meta": {"name": "С якорем", "watch_popups": False},
        "params": {},
        "steps": [
            {"kind": "expect", "args": {"name": "screen1"},
             "any": ['resourceId="com.app:id/title"', 'text="Вход"']},
            {"kind": "click", "args": {},
             "selector": {"call": "click", "args": 'text="Войти"', "fallbacks": []},
             "param": None, "note": "Войти"},
        ],
    })
    код = (scen_dir / "flow_anchor.py").read_text("utf-8")
    assert ('ctx.expect_screen("screen1", any=[dict(resourceId="com.app:id/title"), '
            'dict(text="Вход")])') in код
    assert 'ctx.click(text="Войти")' in код


# --------------------------------------------------------------- правка

def test_рецепт_отдаёт_шаги_записанного_сценария(scen_dir):
    api_recorder.save_scenario({"key": "flow_edit", "meta": META, "steps": STEPS})
    рецепт = api_recorder.recipe("flow_edit")
    assert рецепт["key"] == "flow_edit"
    assert рецепт["meta"]["name"] == "Тест"
    assert рецепт["steps"][0]["kind"] == "unlock"
    assert рецепт["assets"] == {}


def test_позиция_узла_сохраняется_и_возвращается_в_рецепте(scen_dir):
    api_recorder.save_scenario({
        "key": "flow_pos", "meta": META,
        "steps": [{"kind": "unlock", "args": {}, "pos": [40, 80]}],
    })
    рецепт = api_recorder.recipe("flow_pos")
    assert рецепт["steps"][0]["pos"] == [40, 80]


def test_рецепт_чужого_файла_даёт_404(scen_dir):
    (scen_dir / "руками.py").write_text("def run(ctx): pass", "utf-8")
    with pytest.raises(HTTPException) as e:
        api_recorder.recipe("руками")
    assert e.value.status_code == 404


def test_список_помечает_правимые_сценарии(scen_dir):
    api_recorder.save_scenario({"key": "flow_edit", "meta": META, "steps": STEPS})
    (scen_dir / "руками.py").write_text("def run(ctx): pass", "utf-8")
    found = {s["key"]: s for s in api_scenarios.list_scenarios(reload=True)}
    assert found["flow_edit"]["editable"] is True
    assert found["руками"]["editable"] is False


def test_правка_перезаписывает_тот_же_файл(scen_dir):
    api_recorder.save_scenario({"key": "flow_edit", "meta": META, "steps": STEPS})
    api_recorder.save_scenario({
        "key": "flow_edit", "meta": META, "overwrite": True,
        "steps": [{"kind": "key", "args": {"name": "back"}}],
    })
    код = (scen_dir / "flow_edit.py").read_text("utf-8")
    assert 'ctx.key("back")' in код
    assert "ctx.unlock()" not in код
    assert api_recorder.recipe("flow_edit")["steps"][0]["kind"] == "key"
