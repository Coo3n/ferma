"""Запись сгенерированного сценария в папку scenarios/."""
import base64
import json

import pytest

from farm import config
from farm.recorder import save, steps

META = {"name": "Тест", "description": "", "watch_popups": False}
STEPS = [steps.normalize_step({"kind": "unlock", "args": {}})]

КРОП = base64.b64encode("png-байты".encode("utf-8")).decode()

ШАГ_С_КРОПОМ = [steps.normalize_step({
    "kind": "click",
    "selector": {"call": "click", "args": 'text="Ок"'},
    "crop": "01_ok.png",
})]


@pytest.fixture
def scen_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("key", [
    "../../беда", "_скрытый", "Верхний", "с пробелом", "", None, "x" * 49, "9начало",
])
def test_плохой_ключ_отвергается(scen_dir, key):
    with pytest.raises(save.SaveError):
        save.target_path(key)


def test_хороший_ключ_даёт_путь_внутри_папки(scen_dir):
    assert save.target_path("login_flow") == scen_dir / "login_flow.py"


def test_сохранение_создаёт_файл(scen_dir):
    path = save.save("login_flow", META, {}, STEPS)
    assert path.exists()
    assert "ctx.unlock()" in path.read_text("utf-8")


def test_пустой_список_шагов_отвергается(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("login_flow", META, {}, [])


def test_коллизия_без_перезаписи_даёт_Conflict(scen_dir):
    save.save("login_flow", META, {}, STEPS)
    with pytest.raises(save.Conflict):
        save.save("login_flow", META, {}, STEPS)


def test_перезапись_разрешена_явным_флагом(scen_dir):
    save.save("login_flow", META, {}, STEPS)
    other = [steps.normalize_step({"kind": "key", "args": {"name": "back"}})]
    path = save.save("login_flow", META, {}, other, overwrite=True)
    text = path.read_text("utf-8")
    assert 'ctx.key("back")' in text
    assert "ctx.unlock()" not in text


def test_ассеты_сохраняются_рядом_со_сценарием(scen_dir):
    save.save("demo", META, {}, ШАГ_С_КРОПОМ,
              assets={"01_ok.png": КРОП}, screen_width=1080)
    assets = scen_dir / "demo_assets"
    assert (assets / "01_ok.png").read_bytes() == "png-байты".encode("utf-8")
    assert json.loads((assets / "meta.json").read_text("utf-8")) == {"screen_width": 1080}


def test_имя_ассета_с_выходом_из_папки_отвергается(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets={"../побег.png": КРОП})


@pytest.mark.parametrize("плохие_assets", [
    ["01_ok.png"], "01_ok.png", 42,
])
def test_ассеты_не_словарь_отвергаются(scen_dir, плохие_assets):
    """assets не проверялся на тип: список/строка/число давали

    AttributeError/TypeError (HTTP 500) вместо внятного SaveError (400) —
    в модуле, чья единственная работа — валидация.
    """
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets=плохие_assets)


def test_ассет_не_base64_отвергается(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets={"01_ok.png": "не base64!!!"})


def test_битый_ассет_не_оставляет_файл_сценария(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets={"01_ok.png": "не base64!!!"})
    assert not (scen_dir / "demo.py").exists()


def test_удаление_ассетов_сносит_папку(scen_dir):
    save.save("demo", META, {}, ШАГ_С_КРОПОМ,
              assets={"01_ok.png": КРОП}, screen_width=720)
    save.delete_assets("demo")
    assert not (scen_dir / "demo_assets").exists()


def test_удаление_ассетов_у_негодного_ключа_молчит(scen_dir):
    save.delete_assets("../беда")   # не бросает: удаление не должно падать


# ------------------------------------------------------------------ рецепт

def test_рецепт_пишется_рядом_и_читается_обратно(scen_dir):
    save.save("demo", META, {}, STEPS)
    рецепт = save.load_recipe("demo")
    assert рецепт["meta"] == META
    assert рецепт["steps"] == STEPS
    assert save.has_recipe("demo") is True


def test_рецепта_нет_у_чужого_файла(scen_dir):
    (scen_dir / "руками.py").write_text("def run(ctx): pass", "utf-8")
    assert save.has_recipe("руками") is False
    assert save.load_recipe("руками") is None


def test_негодный_ключ_не_роняет_чтение_рецепта(scen_dir):
    assert save.has_recipe("../беда") is False
    assert save.load_recipe("../беда") is None
    assert save.load_assets("../беда") == {}


def test_рецепт_переживает_перезапись(scen_dir):
    save.save("demo", META, {}, STEPS)
    другие = [steps.normalize_step({"kind": "key", "args": {"name": "back"}})]
    save.save("demo", META, {}, другие, overwrite=True)
    assert save.load_recipe("demo")["steps"] == другие


def test_кропы_отдаются_в_base64(scen_dir):
    save.save("demo", META, {}, ШАГ_С_КРОПОМ,
              assets={"01_ok.png": КРОП}, screen_width=1080)
    assert save.load_assets("demo") == {"01_ok.png": КРОП}


def test_перезапись_сносит_старые_кропы(scen_dir):
    """Кропы нумеруются по позиции шага: после правки старый файл уже не

    совпадает со своим шагом, а новый .py на него не ссылается. Оставлять
    такой файл — копить мусор, который вводит в заблуждение при следующей
    правке.
    """
    save.save("demo", META, {}, ШАГ_С_КРОПОМ,
              assets={"01_ok.png": КРОП}, screen_width=1080)
    save.save("demo", META, {}, STEPS, overwrite=True)
    assert not (scen_dir / "demo_assets" / "01_ok.png").exists()
    assert save.load_assets("demo") == {}
