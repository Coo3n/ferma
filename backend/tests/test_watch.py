"""Сторож долгих циклов (ctx.on_track): чужое приложение или застывший экран
→ стражи → вопрос человеку. Устройство не нужно: экран подменяется."""
import json

import pytest

from farm import config, deviations as dv
from farm.context import DeviceContext, StepFailed

PKG = "com.instagram.android"


class Экран:
    """Что «видит» ctx: пакет впереди и тексты экрана."""

    def __init__(self, app=PKG, texts=("пост 1",)):
        self.app = app
        self.texts = list(texts)


class МолчащиеСтражи:
    def try_all(self, ctx):
        return []


def ctx_(monkeypatch, экран, hold=None, tmp_path=None):
    ctx = DeviceContext("s", logger=lambda m: None, hold=hold,
                        artifacts_dir=tmp_path, job_id="abc123", scenario_key="warm")
    monkeypatch.setattr(config, "WATCH", True)
    monkeypatch.setattr(config, "WATCH_EVERY", 0)
    monkeypatch.setattr(config, "WATCH_SAME", 3)
    monkeypatch.setattr(config, "HOLD", True)
    monkeypatch.setattr(ctx, "current_app", lambda: экран.app)
    monkeypatch.setattr(ctx, "_screen_texts", lambda limit=5: list(экран.texts))
    monkeypatch.setattr(ctx, "_obstacle_snapshot",
                        lambda: {"package": экран.app, "texts": list(экран.texts), "candidates": []})
    ctx._guards = МолчащиеСтражи()
    return ctx


def test_живая_лента_не_тревожит(monkeypatch):
    экран = Экран()
    asked = []
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: asked.append(что) or "retry")
    for i in range(10):
        экран.texts = [f"пост {i}"]
        assert ctx.on_track(PKG) is True
    assert asked == []


def test_застывший_экран_зовёт_человека_с_видом_lost(monkeypatch, tmp_path):
    экран = Экран(texts=["Оцените приложение", "Позже"])
    вопросы = []

    def hold(что, kind="", obstacle="", **kw):
        вопросы.append((что, kind, obstacle))
        экран.texts = ["пост 9"]          # человек показал, как закрыть окно
        return "retry"

    ctx = ctx_(monkeypatch, экран, hold=hold, tmp_path=tmp_path)
    assert ctx.on_track(PKG) is True     # 1-й одинаковый экран
    assert ctx.on_track(PKG) is True     # 2-й
    assert ctx.on_track(PKG) is True     # 3-й — тревога, человек поправил
    assert len(вопросы) == 1
    что, kind, obstacle = вопросы[0]
    assert kind == "lost" and "не меняется" in что
    assert obstacle == "obstacle_lost_01.json"
    слепок = json.loads((tmp_path / obstacle).read_text("utf-8"))
    assert слепок["lost"] is True and "Оцените приложение" in слепок["texts"]


def test_чужое_приложение_сразу_тревога(monkeypatch, tmp_path):
    экран = Экран(app="com.android.launcher")
    вопросы = []

    def hold(что, **kw):
        вопросы.append(что)
        экран.app = PKG
        return "retry"

    ctx = ctx_(monkeypatch, экран, hold=hold, tmp_path=tmp_path)
    assert ctx.on_track(PKG) is True
    assert вопросы and "com.android.launcher" in вопросы[0]


def test_не_поправили_спрашивает_снова_и_падает_по_решению(monkeypatch, tmp_path):
    экран = Экран(app="com.other")
    ответы = iter(["retry", "drop"])
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: next(ответы), tmp_path=tmp_path)
    with pytest.raises(StepFailed, match="сбился с пути"):
        ctx.on_track(PKG)


def test_не_обращать_внимания_идёт_дальше(monkeypatch, tmp_path):
    экран = Экран(app="com.other")
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: "skip", tmp_path=tmp_path)
    assert ctx.on_track(PKG) is False


def test_страж_закрыл_окно_человека_не_зовём(monkeypatch, tmp_path):
    экран = Экран(app="com.other")
    asked = []
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: asked.append(1) or "drop",
               tmp_path=tmp_path)

    class Страж:
        def try_all(self, c):
            экран.app = PKG
            return ["закрыть-оценку"]

    ctx._guards = Страж()
    assert ctx.on_track(PKG) is True
    assert asked == []


def test_спросить_некого_пишет_отклонение_и_идёт_дальше(monkeypatch, tmp_path):
    экран = Экран(app="com.other", texts=["Подозрительный вход"])
    записи = []
    monkeypatch.setattr(dv.deviations, "record", lambda **kw: записи.append(kw))
    ctx = ctx_(monkeypatch, экран, hold=None, tmp_path=tmp_path)
    assert ctx.on_track(PKG) is False
    assert записи and записи[0]["kind"] == dv.LOST
    assert записи[0]["obstacle_file"] == "obstacle_lost_01.json"


def test_сторож_смотрит_не_чаще_интервала(monkeypatch):
    экран = Экран(app="com.other")
    asked = []
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: asked.append(1) or "skip")
    monkeypatch.setattr(config, "WATCH_EVERY", 3600)
    ctx._watch_at = -1e9   # «давно не смотрел», независимо от аптайма
    ctx.on_track(PKG)
    ctx.on_track(PKG)
    assert len(asked) == 1


def test_выключенный_сторож_молчит(monkeypatch):
    экран = Экран(app="com.other")
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: "drop")
    monkeypatch.setattr(config, "WATCH", False)
    assert ctx.on_track(PKG) is True


def test_пустой_экран_не_считается_застывшим(monkeypatch):
    экран = Экран(texts=[])
    asked = []
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: asked.append(1) or "skip")
    for _ in range(6):
        ctx.on_track(PKG)
    assert asked == []


def test_потолок_остановок_не_роняет_прогрев(monkeypatch, tmp_path):
    """Человек не отвечал (потолок остановок) — сторож идёт дальше, а не падает."""
    экран = Экран(app="com.other")
    ctx = ctx_(monkeypatch, экран, hold=lambda что, **kw: "retry", tmp_path=tmp_path)
    monkeypatch.setattr(config, "HOLD_MAX_PER_JOB", 0)
    assert ctx.on_track(PKG) is False


def test_сорванный_вопрос_не_роняет_прогрев(monkeypatch, tmp_path):
    экран = Экран(app="com.other")

    def hold(что, **kw):
        raise RuntimeError("очередь недоступна")

    ctx = ctx_(monkeypatch, экран, hold=hold, tmp_path=tmp_path)
    assert ctx.on_track(PKG) is False
