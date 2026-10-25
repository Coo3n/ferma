"""Монитор уведомлений: разбор dumpsys, секретные приложения, список слежения."""
import pytest

from farm import config, notifications
from farm.api import notifications as api_notes

DUMP = """\
  Notification List:
    NotificationRecord(0x0a1b2c3d: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=3 key=0|com.whatsapp|1|null|10123: Notification(channel=msg pri=0 contentView=null vibrate=null sound=null defaults=0x0 flags=0x18 color=0x00000000 category=msg vis=PRIVATE))
      uid=10123 userId=0
      extras={
        android.title=String (Иван)
        android.text=String (Привет, как дела?)
        android.subText=null
      }
    NotificationRecord(0x0e1f2a3b: pkg=com.android.systemui user=UserHandle{0} id=7 tag=null importance=2 key=0|com.android.systemui|7|null|10010: Notification(channel=ALR pri=0 contentView=null vibrate=null sound=null defaults=0x0 flags=0x2 color=0x00000000 vis=PUBLIC))
      extras={
        android.title=String (USB debugging connected)
        android.text=String (Tap to disable)
      }
    NotificationRecord(0x0f2a3b4c: pkg=ru.sberbankmobile user=UserHandle{0} id=3 tag=null importance=3 key=0|ru.sberbankmobile|3|null|10200: Notification(channel=ops pri=0 flags=0x10 vis=PRIVATE))
      extras={
        android.title=String (Сбер)
        android.text=SpannableString (Ваш код 123456)
      }
    NotificationRecord(0x0a0b0c0d: pkg=com.whatsapp user=UserHandle{0} id=2 tag=null importance=3 key=0|com.whatsapp|2|null|10123: Notification(channel=msg flags=0x10))
      extras={
        android.title=String (Мария)
        android.text=null
      }
"""


def test_parse_reads_pkg_title_text_and_drops_ongoing():
    notes = notifications.parse(DUMP)
    assert [(n.pkg, n.title, n.text) for n in notes] == [
        ("com.whatsapp", "Иван", "Привет, как дела?"),
        ("ru.sberbankmobile", "Сбер", "Ваш код 123456"),
        ("com.whatsapp", "Мария", ""),
    ]                                       # flags=0x2 (постоянное) отброшено


def test_parse_garbage_and_empty():
    assert notifications.parse("") == []
    assert notifications.parse(None) == []
    assert notifications.parse("nothing useful here") == []


def test_is_secret():
    for pkg in ("ru.sberbankmobile", "com.tinkoff.bank", "ru.vtb24.mobilebanking.android", "com.google.android.apps.authenticator2"):
        assert notifications.is_secret(pkg), pkg
    assert not notifications.is_secret("com.whatsapp")


@pytest.fixture
def watch_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_WATCH_FILE", tmp_path / "notify_watch.json")
    return tmp_path / "notify_watch.json"


def test_watch_list_round_trip_and_cleaning(watch_file):
    assert notifications.watched() == []
    saved = notifications.set_watched([" com.whatsapp ", "", "com.whatsapp", "org.telegram.messenger", "bad pkg!"])
    assert saved == ["com.whatsapp", "org.telegram.messenger"]
    assert notifications.watched() == saved


def test_watch_file_broken_gives_empty(watch_file):
    watch_file.write_text("{not json", "utf-8")
    assert notifications.watched() == []


def test_scan_phone_filters_packages_and_hides_text_by_default(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell", lambda serial, cmd, timeout=None: DUMP)
    got = notifications.scan_phone("S1", ["com.whatsapp", "ru.sberbankmobile"], show_text=False)
    assert got["count"] == 3
    assert all(set(i) == {"pkg"} for i in got["items"])


def test_scan_phone_shows_text_but_never_for_secret_apps(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell", lambda serial, cmd, timeout=None: DUMP)
    got = notifications.scan_phone("S1", ["com.whatsapp", "ru.sberbankmobile"], show_text=True)
    by_pkg = {}
    for i in got["items"]:
        by_pkg.setdefault(i["pkg"], []).append(i)
    assert by_pkg["com.whatsapp"][0]["title"] == "Иван"
    assert "title" not in by_pkg["ru.sberbankmobile"][0]


def test_scan_phone_empty_packages_means_all(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell", lambda serial, cmd, timeout=None: DUMP)
    assert notifications.scan_phone("S1", [], show_text=False)["count"] == 3


def test_api_watch_get_put(watch_file):
    assert api_notes.get_watch() == {"packages": []}
    assert api_notes.put_watch({"packages": ["com.whatsapp"]}) == {"packages": ["com.whatsapp"]}


def test_api_scan_over_online_phones(monkeypatch, watch_file):
    class D:
        def __init__(self, serial, name):
            self.serial, self.name, self.online = serial, name, True

    monkeypatch.setattr(api_notes.registry, "all", lambda: [D("A", "Т1"), D("B", "Т2")])
    monkeypatch.setattr(api_notes.notifications, "scan_phone",
                        lambda serial, pkgs, show_text: {"count": 1, "items": [{"pkg": "com.whatsapp"}]})
    got = api_notes.scan(packages="com.whatsapp", text=0)
    assert got["A"]["name"] == "Т1" and got["B"]["count"] == 1
