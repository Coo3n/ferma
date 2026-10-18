"""Телефон, пропавший посреди задачи, остаётся занятым до её конца.

Иначе после переподключения он выглядел свободным, и на него ставилась
вторая задача, пока первая ещё шла. Освобождает его runner (finally)."""
from farm import adb
import importlib

from farm.devices import pool

registry_mod = importlib.import_module("farm.devices.registry")


def test_пропавший_телефон_не_освобождается_до_конца_задачи(monkeypatch):
    reg = registry_mod.Registry()
    monkeypatch.setattr(reg, "_read_health", lambda d: None)
    monkeypatch.setattr(pool, "drop", lambda serial: None)
    monkeypatch.setattr(registry_mod.net, "all", lambda: [])
    found = [adb.AdbDevice(serial="s1", state="device")]
    monkeypatch.setattr(adb, "list_devices", lambda: list(found))

    reg.refresh_once()
    assert reg.acquire("s1", "job1")

    found.clear()                       # кабель выдернули посреди задачи
    reg.refresh_once()
    found.append(adb.AdbDevice(serial="s1", state="device"))
    reg.refresh_once()                  # вернулся

    assert not reg.acquire("s1", "job2"), "занят первой задачей"
    reg.release("s1", "job1")
    assert reg.acquire("s1", "job2")
