"""Стражи: загрузка файлов, срабатывание, лимиты. Экран — фейковый ctx."""
import json

import pytest

from farm import config, guards


class ФейкCtx:
    """Экран — список «видимых» селекторов. Клик убирает попап с экрана."""

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

    def current_app(self):
        return self.app

    def log(self, message):
        self.lines.append(message)


ПОПАП = {
    "name": "permission-ru",
    "when": {"any": [{"text": "Разрешить"}]},
    "action": {"click": {"text": "Разрешить"}},
}


def записать(dirpath, name, data):
    (dirpath / name).write_text(json.dumps(data, ensure_ascii=False), "utf-8")


@pytest.fixture
def guards_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GUARDS_DIR", tmp_path)
    guards._cache.clear()
    return tmp_path


def test_страж_срабатывает_и_докладывает(guards_dir):
    записать(guards_dir, "global.json", [ПОПАП])
    ctx = ФейкCtx(screen=[{"text": "Разрешить"}])
    assert guards.GuardEngine().try_all(ctx) == ["permission-ru"]
    assert ctx.actions == [("click", {"text": "Разрешить"})]


def test_max_fires_обрывает_цикл(guards_dir):
    записать(guards_dir, "global.json", [dict(ПОПАП, max_fires=2)])
    engine = guards.GuardEngine()
    for ожидаемо in (["permission-ru"], ["permission-ru"], []):
        assert engine.try_all(ФейкCtx(screen=[{"text": "Разрешить"}])) == ожидаемо


def test_max_fires_считает_попытки_а_не_успехи(guards_dir):
    """Страж, чей when совпадает, а action промахивается (см. правку 1 —

    капс/локаль расходятся), обязан исчерпать max_fires и перестать
    проверяться. До правки счётчик рос только внутри `if _apply(...)` —
    страж без единого успешного клика проверялся бы на каждом _rescue()
    бесконечно.
    """
    БИТЫЙ = {
        "name": "битый",
        "when": {"any": [{"text": "РАЗРЕШИТЬ"}]},
        "action": {"click": {"text": "Разрешить"}},  # регистр не совпадает — промах
        "max_fires": 2,
    }
    записать(guards_dir, "global.json", [БИТЫЙ])
    engine = guards.GuardEngine()
    ctx = ФейкCtx(screen=[{"text": "РАЗРЕШИТЬ"}])
    for _ in range(5):
        assert engine.try_all(ctx) == []
    assert engine._fired["битый"] == 2


def test_страж_пакета_молчит_в_чужом_приложении(guards_dir):
    записать(guards_dir, "global.json", [])
    записать(guards_dir, "com.example.json", [{
        "name": "rate-us",
        "when": {"any": [{"textContains": "Оцени"}]},
        "action": {"key": "back"},
    }])
    экран = [{"textContains": "Оцени"}]
    assert guards.GuardEngine().try_all(ФейкCtx(экран, app="com.other")) == []
    ctx = ФейкCtx(экран, app="com.example")
    assert guards.GuardEngine().try_all(ctx) == ["rate-us"]
    assert ctx.actions == [("key", "back")]


def test_битый_страж_пропускается_годный_остаётся(guards_dir):
    записать(guards_dir, "global.json", [
        {"name": "без-действия", "when": {"any": [{"text": "x"}]}},
        ПОПАП,
    ])
    assert [g.name for g in guards.load()] == ["permission-ru"]


def test_битый_json_даёт_пустой_список(guards_dir):
    (guards_dir / "global.json").write_text("{битый", "utf-8")
    assert guards.load() == []


def test_отсутствие_файла_не_ошибка(guards_dir):
    assert guards.load("com.нет.такого") == []


def test_комплект_из_коробки_грузится_целиком():
    """Дефолтный global.json обязан пройти проверку весь, без пропусков."""
    guards._cache.clear()
    path = config.ROOT / "guards" / "global.json"
    raw = json.loads(path.read_text("utf-8"))
    loaded = guards._load_file(path)
    assert len(loaded) == len(raw) >= 4
    assert len({g.name for g in loaded}) == len(loaded)


def test_стражи_закрывают_всё_что_распознают():
    """Инвариант: action.click обязан матчить любой текст, на который

    срабатывает when. Раньше три стража (permission-allow-ru/en, anr-wait)
    распознавали оба варианта (капс/локаль), а закрывали только один —
    страж срабатывал вхолостую на MIUI (капс) и на английской прошивке.
    """
    import re

    path = config.ROOT / "guards" / "global.json"
    by_name = {g["name"]: g for g in json.loads(path.read_text("utf-8"))}
    примеры = {
        "permission-allow-ru": ["Разрешить", "РАЗРЕШИТЬ"],
        "permission-allow-en": ["Allow", "ALLOW"],
        "anr-wait": ["Подождать", "Wait"],
    }
    for name, тексты in примеры.items():
        pattern = by_name[name]["action"]["click"]["textMatches"]
        for text in тексты:
            assert re.fullmatch(pattern, text), f"{name}: {pattern!r} не матчит {text!r}"
