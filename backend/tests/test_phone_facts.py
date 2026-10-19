"""Факты о телефоне: разбор вывода dumpsys/df, сравнение версий."""
import pytest

from farm.control import facts

DUMPSYS = """Packages:
  Package [com.vkontakte.android] (5c1d2e):
    userId=10213
    versionCode=24015 minSdk=26 targetSdk=34
    versionName=8.40.1
  Hidden system packages:
    versionCode=100 minSdk=21
    versionName=1.0
"""

DF_TOYBOX = """Filesystem       1K-blocks    Used Available Use% Mounted on
/dev/block/dm-8  114639928 6553676 108086252   6% /data
"""

DF_OLD = """Filesystem               Size     Used     Free   Blksize
/data                   25.0G     6.0G    19.5G   4096
"""


def test_версия_приложения():
    assert facts.parse_app_version(DUMPSYS) == {"name": "8.40.1", "code": 24015}


def test_не_установлено():
    assert facts.parse_app_version("Unable to find package: com.nope\n") is None


@pytest.mark.parametrize("text,gb", [(DF_TOYBOX, 103.08), (DF_OLD, 19.5)])
def test_свободное_место(text, gb):
    assert facts.parse_free_gb(text) == pytest.approx(gb, abs=0.01)


def test_место_не_разобрать():
    assert facts.parse_free_gb("df: /data: Permission denied") is None


@pytest.mark.parametrize("have,want,lt", [
    ("8.38.2", "8.40", True), ("8.40", "8.40", False), ("8.40.1", "8.40", False),
    ("10.0", "9.9.9", False), ("8.40-beta", "8.41", True), ("v8.4", "8.40", True),
])
def test_сравнение_версий(have, want, lt):
    assert facts.version_lt(have, want) is lt


def test_нечитаемая_версия():
    with pytest.raises(ValueError, match="не понять версию"):
        facts.version_lt("beta", "8.40")


def test_интернет(monkeypatch):
    monkeypatch.setattr(facts.adb, "shell", lambda serial, cmd, timeout=None: "0\n")
    assert facts.online("S") is True
    monkeypatch.setattr(facts.adb, "shell", lambda serial, cmd, timeout=None: "1\n")
    assert facts.online("S") is False


def test_заряд(monkeypatch):
    monkeypatch.setattr(facts.adb, "battery", lambda serial: {"level": 17})
    assert facts.battery_level("S") == 17
    monkeypatch.setattr(facts.adb, "battery", lambda serial: {})
    with pytest.raises(facts.FactUnknown):
        facts.battery_level("S")


@pytest.mark.parametrize("text", ["", "\n", "Error: something odd\n", "Packages:\n"])
def test_пустой_ответ_не_значит_не_установлено(text):
    with pytest.raises(facts.FactUnknown):
        facts.parse_app_version(text)


def test_регулярки_не_пускают_перевод_строки():
    from farm import apklib
    from farm.recorder import steps
    assert not apklib.PACKAGE_RE.match("com.a.b\n")
    assert not steps.VERSION_RE.match("1.2\n")
