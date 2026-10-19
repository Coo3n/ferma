"""Горит ли экран и висит ли блокировка — разбор dumpsys.

Образцы собраны по формату AOSP, который One UI (Samsung) и MIUI/HyperOS
(Xiaomi) сохраняют; на живых телефонах эти тексты не снимались.
"""
from farm import adb

# Samsung One UI: экран горит, блокировка висит.
SAMSUNG_LOCKED = """  mWakefulness=Awake
Display Power: state=ON
    KeyguardServiceDelegate
      showing=true
      inputRestricted=true
      occluded=false
      secure=true
"""

# Samsung с Always On Display: часы на чёрном экране.
SAMSUNG_AOD = """  mWakefulness=Dozing
Display Power: state=DOZE
    KeyguardServiceDelegate
      showing=true
"""

# Xiaomi MIUI: разблокирован и работает.
XIAOMI_OPEN = """  mWakefulness=Awake
Display Power: state=ON
    KeyguardServiceDelegate
      showing=false
      occluded=false
"""


def test_samsung_заблокирован():
    assert adb.parse_screen_state(SAMSUNG_LOCKED) == {"on": True, "locked": True, "known": True}


def test_samsung_aod_это_выключен():
    assert adb.parse_screen_state(SAMSUNG_AOD)["on"] is False


def test_xiaomi_разблокирован():
    assert adb.parse_screen_state(XIAOMI_OPEN) == {"on": True, "locked": False, "known": True}


def test_погашен():
    out = "  mWakefulness=Asleep\nDisplay Power: state=OFF\n"
    assert adb.parse_screen_state(out)["on"] is False


def test_старая_прошивка_mshowinglockscreen():
    out = "mWakefulness=Awake\n    mShowingLockscreen=true mShowingDream=false\n"
    assert adb.parse_screen_state(out)["locked"] is True


def test_showing_вне_блока_keyguard_не_блокировка():
    out = """mWakefulness=Awake
    KeyguardServiceDelegate
      showing=false
    SomeOtherPanel
      showing=true
"""
    assert adb.parse_screen_state(out)["locked"] is False


def test_без_mwakefulness_по_display_power():
    assert adb.parse_screen_state("Display Power: state=OFF\n")["on"] is False
    assert adb.parse_screen_state("Display Power: state=ON\n")["on"] is True


def test_ничего_не_нашли_неизвестно():
    assert adb.parse_screen_state("")["known"] is False


def test_неизвестно_не_пугаем_плашкой(monkeypatch):
    # grep не сработал и полный дамп пуст — плашку не показываем вовсе.
    monkeypatch.setattr(adb, "shell", lambda s, cmd, timeout=None: "")
    assert adb.screen_state("X") is None


def test_без_grep_разбирает_полный_дамп(monkeypatch):
    calls = []

    def fake(serial, cmd, timeout=None):
        calls.append(cmd)
        return "grep: not found\n" if len(calls) == 1 else SAMSUNG_LOCKED

    monkeypatch.setattr(adb, "shell", fake)
    assert adb.screen_state("X") == {"on": True, "locked": True}
    assert len(calls) == 2
