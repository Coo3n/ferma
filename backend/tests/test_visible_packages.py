"""Системные приложения со значком (Настройки, Галерея) попадают в списки
пульта и сценариев; служебные пакеты без значка — нет."""
from farm import adb

LAUNCHER_OUT = """57 activities found:
  Activity #0:
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    com.android.camera/.Camera
  Activity #1:
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    com.android.settings/.Settings
  Activity #2:
    priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=true
    com.miui.gallery/.activity.HomePageStartupHelper$Activity
"""


def test_visible_packages_adds_launchable_system_apps(monkeypatch):
    def fake_shell(serial, args, timeout=None):
        if args[:2] == ["cmd", "package"]:
            return LAUNCHER_OUT
        if "-3" in args:
            return "package:com.vkontakte.android\npackage:com.android.camera\n"
        return "package:com.android.systemui\n"

    monkeypatch.setattr(adb, "shell", fake_shell)
    assert adb.launchable_packages("x") == ["com.android.camera", "com.android.settings", "com.miui.gallery"]
    assert adb.visible_packages("x") == [
        "com.android.camera", "com.android.settings", "com.miui.gallery", "com.vkontakte.android"]


def test_launchable_packages_survives_adb_error(monkeypatch):
    def broken(serial, args, timeout=None):
        raise adb.AdbError("нет связи")

    monkeypatch.setattr(adb, "shell", broken)
    assert adb.launchable_packages("x") == []
