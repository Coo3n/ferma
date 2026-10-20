"""Схема новых шагов: блок «Если на телефоне» и «Приложение готово»."""
import pytest

from farm.recorder import steps


def phone(**args):
    return steps.normalize_step({"kind": "if_phone", "args": {"span": 1, **args}})


def test_приложение_есть():
    s = phone(check="app_installed", package="com.vk.app", percent=50)
    assert s["args"] == {"span": 1, "check": "app_installed", "package": "com.vk.app",
                         "negate": False}


def test_версия_ниже():
    s = phone(check="app_older", package="com.vk.app", version="8.40", negate=True)
    assert s["args"]["version"] == "8.40" and s["args"]["negate"] is True


@pytest.mark.parametrize("args,msg", [
    ({"check": "dance"}, "условие"),
    ({"check": "app_installed"}, "приложение"),
    ({"check": "app_installed", "package": "vk"}, "приложение"),
    ({"check": "app_older", "package": "com.vk.app", "version": "новая"}, "версия"),
    ({"check": "battery_below", "percent": 0}, "заряд"),
    ({"check": "space_below", "gb": 0}, "место"),
    ({"check": "no_account", "platform": "ok"}, "аккаунт"),
])
def test_ошибки_понятные(args, msg):
    with pytest.raises(steps.StepError, match=msg):
        phone(**args)


def test_заряд_и_место_числа():
    assert phone(check="battery_below", percent="20")["args"]["percent"] == 20
    assert phone(check="space_below", gb="1.5")["args"]["gb"] == 1.5
    assert phone(check="offline")["args"] == {"span": 1, "check": "offline", "negate": False}
    assert phone(check="no_account", platform="vk")["args"]["platform"] == "vk"


def test_блок_вкладывается_как_остальные():
    items = steps.normalize_steps([
        {"kind": "if_phone", "args": {"span": 3, "check": "offline"}},
        {"kind": "sleep", "args": {"seconds": 1}},
        {"kind": "if_seen", "args": {"span": 1}, "any": ['text="OK"']},
        {"kind": "sleep", "args": {"seconds": 1}},
    ])
    assert items[0]["kind"] == "if_phone"
    with pytest.raises(steps.StepError, match="за концом"):
        steps.normalize_steps([{"kind": "if_phone", "args": {"span": 1, "check": "offline"}}])


def test_приложение_готово():
    s = steps.normalize_step({"kind": "ensure_app", "args": {"package": "com.vk.app"}})
    assert s["args"] == {"package": "com.vk.app", "install": True}
    s = steps.normalize_step({"kind": "ensure_app",
                              "args": {"package": "com.vk.app", "min_version": "8.40",
                                       "install": False}, "optional": True})
    assert s["args"] == {"package": "com.vk.app", "min_version": "8.40", "install": False}
    assert s["optional"] is True
    s = steps.normalize_step({"kind": "ensure_app",
                              "args": {"package": "com.vk.app", "min_version": ""}})
    assert "min_version" not in s["args"]
    with pytest.raises(steps.StepError, match="версия"):
        steps.normalize_step({"kind": "ensure_app",
                              "args": {"package": "com.vk.app", "min_version": "x"}})


def test_подписи():
    assert steps.label_of(phone(check="app_installed", package="com.vk.app",
                                negate=True)) == "Если на телефоне нет: com.vk.app"
    assert steps.label_of(phone(check="battery_below", percent=20)) == \
        "Если на телефоне: заряд меньше 20%"
    assert steps.label_of(steps.normalize_step(
        {"kind": "ensure_app", "args": {"package": "com.vk.app", "min_version": "8.40"}})) == \
        "Приложение готово: com.vk.app не ниже 8.40"


def test_схема_для_помощников():
    data = steps.schema()
    assert data["phone_checks"]["app_older"] == ["package", "version"]
    assert "if_phone" in data["blocks"] and "ensure_app" in data["flexible"]
