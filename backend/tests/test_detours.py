"""Отводы: страж зовёт блок, общий выход из незнакомого экрана.

Устройство не нужно: ctx фейковый, экран — список «видимых» селекторов.
"""
import json

import pytest

from farm import config, guards
from farm.context import DeviceContext, StepFailed


class ФейкCtx:
    def __init__(self, screen, app=""):
        self.screen = list(screen)
        self.app = app
        self.actions = []
        self.lines = []

    def exists(self, timeout=0, **sel):
        return sel in self.screen

    def click_if_exists(self, timeout=0, **sel):
        if sel in self.screen:
            self.screen.remove(sel)
            self.actions.append(("click", sel))
            return True
        return False

    def key(self, name):
        self.actions.append(("key", name))

    def run(self, key, **params):
        self.actions.append(("run", key))
        self.screen.clear()          # блок закрыл преграду

    def current_app(self):
        return self.app

    def log(self, message):
        self.lines.append(message)


@pytest.fixture
def guards_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GUARDS_DIR", tmp_path)
    guards._cache.clear()
    return tmp_path


def записать(d, name, data):
    (d / name).write_text(json.dumps(data, ensure_ascii=False), "utf-8")


ОТВОД = {
    "name": "ab-тариф",
    "when": {"any": [{"textContains": "Выберите тариф"}]},
    "action": {"run": "close_tariff"},
}


def test_страж_зовёт_блок(guards_dir):
    записать(guards_dir, "global.json", [ОТВОД])
    ctx = ФейкCtx(screen=[{"textContains": "Выберите тариф"}])
    assert guards.GuardEngine().try_all(ctx) == ["ab-тариф"]
    assert ctx.actions == [("run", "close_tariff")]


def test_имя_блока_обязано_быть_строкой(guards_dir):
    записать(guards_dir, "global.json", [dict(ОТВОД, action={"run": ""})])
    assert guards.load() == []


def test_упавший_блок_не_роняет_остальных_стражей(guards_dir):
    записать(guards_dir, "global.json", [ОТВОД])

    class Падучий(ФейкCtx):
        def run(self, key, **params):
            raise StepFailed("внутри блока всё плохо")

    ctx = Падучий(screen=[{"textContains": "Выберите тариф"}])
    # страж не сработал, но и не уронил разбор: движок вернул пустой список
    assert guards.GuardEngine().try_all(ctx) == []


# ------------------------------------------------------------------ общий выход

class ВыходCtx(DeviceContext):
    """ctx, у которого экран «отпускает» после нужного числа попыток выхода."""

    def __init__(self, освободить_после):
        super().__init__("s", logger=lambda m: None)
        self.освободить_после = освободить_после
        self.попытки = []

    def _obstacle_snapshot(self):
        """Без телефона дамп не снять: настоящий ушёл бы в adb на 20 секунд."""
        return {"package": "com.app", "texts": ["Реклама"],
                "candidates": [{"selector": {"textContains": "Реклама"},
                                "label": "по тексту: «Реклама»"}]}

    def key(self, name):
        self.попытки.append(name)

    def click_if_exists(self, timeout=2, **selector):
        self.попытки.append(selector)
        return False

    def exists(self, timeout=2, **selector):
        return len(self.попытки) >= self.освободить_после


def test_выход_нажимает_назад_первым():
    ctx = ВыходCtx(освободить_после=1)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is True
    assert ctx.попытки[0] == "back"


def test_выход_перебирает_варианты_пока_не_освободит():
    ctx = ВыходCtx(освободить_после=3)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is True
    assert len(ctx.попытки) == 3


def test_выход_сдаётся_и_не_зацикливается():
    ctx = ВыходCtx(освободить_после=999)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is False
    assert len(ctx.попытки) <= 8, "перебор должен быть ограничен"


def test_выход_выключается_настройкой(monkeypatch):
    monkeypatch.setattr(config, "ESCAPE", False)
    ctx = ВыходCtx(освободить_после=1)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is False
    assert ctx.попытки == []


def test_якорь_спасается_общим_выходом(monkeypatch):
    """Стражи промолчали, но экран закрылся кнопкой «Пропустить»."""
    ctx = DeviceContext("s", logger=lambda m: None)
    состояние = {"свободен": False}
    monkeypatch.setattr(ctx, "_rescue", lambda: False)
    monkeypatch.setattr(ctx, "_obstacle_snapshot", lambda: {})
    monkeypatch.setattr(ctx, "exists",
                        lambda timeout=2, **sel: состояние["свободен"])
    monkeypatch.setattr(ctx, "key", lambda name: None)

    def клик(timeout=2, **selector):
        состояние["свободен"] = True   # «Пропустить» закрыл преграду
        return True
    monkeypatch.setattr(ctx, "click_if_exists", клик)

    ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0.1)


def test_якорь_падает_когда_и_выход_не_помог(monkeypatch):
    ctx = DeviceContext("s", logger=lambda m: None)
    monkeypatch.setattr(ctx, "_rescue", lambda: False)
    monkeypatch.setattr(ctx, "_obstacle_snapshot", lambda: {})
    monkeypatch.setattr(ctx, "exists", lambda timeout=2, **sel: False)
    monkeypatch.setattr(ctx, "key", lambda name: None)
    monkeypatch.setattr(ctx, "click_if_exists", lambda timeout=2, **sel: False)
    monkeypatch.setattr(ctx, "current_app", lambda: "com.app.main")
    monkeypatch.setattr(ctx, "_screen_texts", lambda limit=5: ["Реклама"])
    monkeypatch.setattr(ctx, "_expect_artifacts", lambda name: None)
    with pytest.raises(StepFailed, match="ожидал экран"):
        ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0.1)
