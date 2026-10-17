"""Теги телефонов: реестр и эндпоинты (TestClient недоступен — зовём функции роутера)."""
import json

import pytest

from farm.api import bulk as api_bulk
from farm.api import devices as api_devices
import importlib

reg_mod = importlib.import_module("farm.devices.registry")   # пакет затеняет модуль объектом registry
Device, Registry = reg_mod.Device, reg_mod.Registry


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(reg_mod, "TAGS_FILE", tmp_path / "tags.json")
    monkeypatch.setattr(reg_mod, "GROUPS_FILE", tmp_path / "groups.json")
    monkeypatch.setattr(reg_mod, "LABELS_FILE", tmp_path / "devices.json")
    r = Registry()
    r._devices["A"] = Device(serial="A", state="device")
    r._devices["B"] = Device(serial="B", state="device")
    monkeypatch.setattr(api_devices, "registry", r)
    monkeypatch.setattr(api_bulk, "registry", r)
    return r


def test_set_чистит_и_убирает_повторы(reg):
    assert reg.set_tags("A", ["  прогрет ", "Прогрет", "", "новый  телефон"]) == ["прогрет", "новый телефон"]
    assert reg.get("A").tags == ["прогрет", "новый телефон"]


def test_лимиты(reg):
    tags = reg.set_tags("A", [f"t{i}" for i in range(15)] + ["x" * 40])
    assert len(tags) == 10
    assert reg.set_tags("B", ["я" * 30]) == ["я" * 24]


def test_add_remove(reg):
    reg.set_tags("A", ["a"])
    assert reg.add_tags("A", ["b", "A"]) == ["a", "b"]
    assert reg.remove_tags("A", ["A"]) == ["b"]
    assert reg.remove_tags("A", ["b"]) == []


def test_сохраняется_и_грузится(reg, tmp_path):
    reg.set_tags("A", ["vk"])
    reg.set_tags("B", ["inst", "vk"])
    assert json.loads((tmp_path / "tags.json").read_text("utf-8")) == {"A": ["vk"], "B": ["inst", "vk"]}
    reg.set_tags("B", [])
    assert "B" not in json.loads((tmp_path / "tags.json").read_text("utf-8"))
    fresh = Registry()
    assert fresh.tags_of("A") == ["vk"]
    assert fresh.all_tags() == ["vk"]


def test_все_теги_и_to_dict(reg, monkeypatch):
    reg.set_tags("A", ["Б", "а"])
    assert reg.all_tags() == ["а", "Б"]
    monkeypatch.setattr(reg_mod.pool, "is_connected", lambda s: False)
    from farm import accounts
    monkeypatch.setattr(accounts, "summary_for", lambda s: {})
    assert reg.get("A").to_dict()["tags"] == ["Б", "а"]


def test_api(reg):
    assert api_devices.set_tags("A", ["x", "x", "y"]) == {"ok": True, "tags": ["x", "y"]}
    res = api_bulk.bulk_tags(serials=["A", "B", "A"], add=["z"], remove=["x"])
    assert res["ok"]
    assert reg.tags_of("A") == ["y", "z"]
    assert reg.tags_of("B") == ["z"]
    assert api_devices.all_tags() == ["y", "z"]
