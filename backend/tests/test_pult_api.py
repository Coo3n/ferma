"""Пульт телефона: поворот, скриншот, видео экрана (без телефона — adb подменён)."""
import importlib

import pytest
from fastapi import HTTPException

from farm.api import screen as api_screen

reg_mod = importlib.import_module("farm.devices.registry")
Device, Registry = reg_mod.Device, reg_mod.Registry


@pytest.fixture
def phone(tmp_path, monkeypatch):
    monkeypatch.setattr(reg_mod, "TAGS_FILE", tmp_path / "tags.json")
    monkeypatch.setattr(reg_mod, "GROUPS_FILE", tmp_path / "groups.json")
    monkeypatch.setattr(reg_mod, "LABELS_FILE", tmp_path / "devices.json")
    r = Registry()
    r._devices["A"] = Device(serial="A", state="device", label="Phone 1")
    monkeypatch.setattr(api_screen, "registry", r)
    monkeypatch.setattr(api_screen, "RECORDINGS", tmp_path / "rec")
    api_screen._records.clear()
    shell = []
    monkeypatch.setattr(api_screen.adb, "shell", lambda s, cmd, timeout=None: shell.append(cmd) or "0\n")
    return shell


def test_поворот_книжный_в_альбомный(phone):
    res = api_screen.action("A", {"type": "rotate"})
    assert res["landscape"] is True
    assert "settings put system accelerometer_rotation 0" in phone
    assert "settings put system user_rotation 1" in phone


def test_скриншот_отдаётся_файлом(phone, monkeypatch):
    monkeypatch.setattr(api_screen.adb, "exec_out", lambda s, cmd, timeout=None: b"\x89PNG")
    res = api_screen.screenshot("A")
    assert res.body == b"\x89PNG"
    assert "Phone_1_" in res.headers["content-disposition"]


class Proc:
    def __init__(self):
        self.done = False

    def poll(self):
        return 0 if self.done else None

    def wait(self, timeout=None):
        self.done = True

    def kill(self):
        self.done = True


def test_видео_старт_стоп_и_скачивание(phone, monkeypatch, tmp_path):
    monkeypatch.setattr(api_screen.subprocess, "Popen", lambda *a, **kw: Proc())
    monkeypatch.setattr(api_screen.time, "sleep", lambda s: None)

    def pull(args, serial=None, timeout=None):
        dest = args[2]
        open(dest, "wb").write(b"mp4")
    monkeypatch.setattr(api_screen.adb, "raw", pull)

    api_screen.record_start("A")
    assert api_screen.record_state("A")["recording"] is True
    with pytest.raises(HTTPException):
        api_screen.record_start("A")          # вторая запись на тот же телефон
    res = api_screen.record_stop("A")
    assert res["file"].endswith(".mp4") and res["url"].startswith("/api/recordings/")
    assert "pkill -INT screenrecord" in phone
    assert api_screen.record_state("A")["recording"] is False
    assert str(api_screen.recording(res["file"]).path).endswith(res["file"])


def test_видео_не_отдаёт_чужие_файлы(phone):
    with pytest.raises(HTTPException):
        api_screen.recording("../../farm.db")


def test_остановка_без_записи_409(phone):
    with pytest.raises(HTTPException) as e:
        api_screen.record_stop("A")
    assert e.value.status_code == 409


def test_скриншот_с_русским_именем_телефона(phone, monkeypatch):
    api_screen.registry.get("A").label = "Телефон 3"
    monkeypatch.setattr(api_screen.adb, "exec_out", lambda s, cmd, timeout=None: b"\x89PNG")
    res = api_screen.screenshot("A")
    res.headers["content-disposition"].encode("latin-1")   # заголовок обязан быть latin-1
    assert "filename*=UTF-8''" in res.headers["content-disposition"]


def test_повторная_остановка_видео_отклоняется(phone, monkeypatch):
    monkeypatch.setattr(api_screen.subprocess, "Popen", lambda *a, **kw: Proc())
    api_screen.record_start("A")
    api_screen._records["A"]["stopping"] = True
    with pytest.raises(HTTPException) as e:
        api_screen.record_stop("A")
    assert e.value.status_code == 409


def test_клавиша_с_командой_не_уходит_в_shell(phone, monkeypatch):
    """`input keyevent` идёт через sh телефона: хвост после «;» стал бы командой."""
    from farm.control import input as inp
    monkeypatch.setattr(inp, "via_u2", lambda serial, fn: False)
    monkeypatch.setattr(inp.adb, "shell", lambda s, cmd, timeout=None: phone.append(cmd))
    with pytest.raises(HTTPException) as e:
        api_screen.action("A", {"type": "key", "name": "KEYCODE_HOME; reboot"})
    assert e.value.status_code == 400
    assert phone == []
    api_screen.action("A", {"type": "key", "name": "keycode_camera"})
    assert phone == [["input", "keyevent", "KEYCODE_CAMERA"]]


def test_кривые_координаты_это_400(phone):
    with pytest.raises(HTTPException) as e:
        api_screen.action("A", {"type": "tap", "x": "abc", "y": 0.5})
    assert e.value.status_code == 400
