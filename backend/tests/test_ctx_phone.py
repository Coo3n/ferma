"""Проверки телефона в сценарии: факты, установка из библиотеки, ошибки словами."""
import pytest

from farm import accounts, apklib
from farm.adb import AdbError
from farm.context import Cancelled, DeviceContext, StepFailed
from farm.control import facts

PKG = "com.vkontakte.android"


@pytest.fixture
def ctx(monkeypatch):
    lines = []
    c = DeviceContext("S", logger=lines.append)
    c.lines = lines
    monkeypatch.setattr(c, "sleep", lambda s: None)
    monkeypatch.setattr(apklib, "name_of", lambda p: "VK")
    return c


def versions(monkeypatch, *seq):
    """app_version отдаёт значения по очереди (исключение — бросает)."""
    it = iter(seq)

    def fake(serial, package):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(facts, "app_version", fake)


def test_есть_приложение(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.38.2", "code": 1})
    assert ctx.phone_is("app_installed", package=PKG) is True
    assert "VK есть, 8.38.2" in ctx.lines[-1]


def test_версия_ниже_и_нет_приложения(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.38.2", "code": 1}, None)
    assert ctx.phone_is("app_older", package=PKG, version="8.40") is True
    assert ctx.phone_is("app_older", package=PKG, version="8.40") is True   # нет = старее


@pytest.mark.parametrize("check,kw,fact,value,want", [
    ("battery_below", {"percent": 20}, "battery_level", 17, True),
    ("battery_below", {"percent": 20}, "battery_level", 80, False),
    ("offline", {}, "online", False, True),
    ("space_below", {"gb": 1}, "free_gb", 0.4, True),
])
def test_факты(ctx, monkeypatch, check, kw, fact, value, want):
    monkeypatch.setattr(facts, fact, lambda serial: value)
    assert ctx.phone_is(check, **kw) is want


def test_аккаунт(ctx, monkeypatch):
    monkeypatch.setattr(accounts, "for_device", lambda serial, platform: None)
    assert ctx.phone_is("no_account", platform="vk") is True


def test_один_повтор_потом_понятная_ошибка(ctx, monkeypatch):
    versions(monkeypatch, AdbError("timeout"), {"name": "1.0", "code": 1})
    assert ctx.phone_is("app_installed", package=PKG) is True
    versions(monkeypatch, AdbError("timeout"), AdbError("timeout"))
    with pytest.raises(StepFailed, match="не удалось узнать версию"):
        ctx.phone_is("app_installed", package=PKG)


def test_уже_готово(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.41", "code": 1})
    monkeypatch.setattr(apklib, "install", lambda *a, **k: pytest.fail("не ставить"))
    ctx.ensure_app(PKG, min_version="8.40")


def test_нет_ставим_из_библиотеки(ctx, monkeypatch):
    versions(monkeypatch, None, {"name": "8.40", "code": 1})
    monkeypatch.setattr(apklib, "get", lambda p: {"package": p, "version_name": "8.40"})
    calls = []
    monkeypatch.setattr(apklib, "install",
                        lambda serial, package, check_cancel: calls.append(package) or "Success")
    ctx.ensure_app(PKG)
    assert calls == [PKG]
    assert any("ставлю 8.40" in line for line in ctx.lines)


def test_только_проверка(ctx, monkeypatch):
    versions(monkeypatch, None)
    with pytest.raises(StepFailed, match="VK не установлен"):
        ctx.ensure_app(PKG, install=False)


def test_нет_в_библиотеке(ctx, monkeypatch):
    versions(monkeypatch, None)
    monkeypatch.setattr(apklib, "get", lambda p: None)
    with pytest.raises(StepFailed, match="Сценарии → Приложения"):
        ctx.ensure_app(PKG)


def test_в_библиотеке_старее_нужной(ctx, monkeypatch):
    versions(monkeypatch, {"name": "8.20", "code": 1})
    monkeypatch.setattr(apklib, "get", lambda p: {"package": p, "version_name": "8.30"})
    monkeypatch.setattr(apklib, "install", lambda *a, **k: pytest.fail("не ставить"))
    with pytest.raises(StepFailed, match="в библиотеке VK 8.30, а нужно не ниже 8.40"):
        ctx.ensure_app(PKG, min_version="8.40")


def test_установка_упала(ctx, monkeypatch):
    versions(monkeypatch, None)
    monkeypatch.setattr(apklib, "get", lambda p: {"package": p, "version_name": "8.40"})

    def boom(serial, package, check_cancel):
        raise apklib.InstallFailed("на телефоне не хватило места")

    monkeypatch.setattr(apklib, "install", boom)
    with pytest.raises(StepFailed, match="VK: на телефоне не хватило места"):
        ctx.ensure_app(PKG)


def test_отмена(monkeypatch):
    c = DeviceContext("S", logger=lambda m: None, cancel_check=lambda: True)
    with pytest.raises(Cancelled):
        c.ensure_app(PKG)
