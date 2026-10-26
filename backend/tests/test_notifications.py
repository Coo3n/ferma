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
    assert "title" not in by_pkg["com.whatsapp"][0]          # мессенджер скрыт
    assert "title" not in by_pkg["ru.sberbankmobile"][0]


def _dump(pkg, title, text):
    return (f"    NotificationRecord(0x0a1b2c3d: pkg={pkg} user=UserHandle{{0}} id=1 tag=null "
            f"importance=3 key=k: Notification(channel=c flags=0x10))\n"
            f"      extras={{\n        android.title=String ({title})\n"
            f"        android.text=String ({text})\n      }}\n")


def test_scan_phone_shows_plain_text_of_ordinary_app(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell",
                        lambda s, c, timeout=None: _dump("com.example.news", "Новость", "Вышла версия"))
    item = notifications.scan_phone("S1", [], show_text=True)["items"][0]
    assert item["title"] == "Новость" and item["text"] == "Вышла версия"


@pytest.mark.parametrize("pkg", [
    "com.google.android.apps.messaging", "com.android.mms", "org.telegram.messenger",
    "com.whatsapp", "com.viber.voip", "org.thoughtcrime.securesms.signal", "com.samsung.sms"])
def test_messaging_apps_hide_text(monkeypatch, pkg):
    monkeypatch.setattr(notifications.adb, "shell", lambda s, c, timeout=None: _dump(pkg, "Мама", "привет"))
    assert set(notifications.scan_phone("S1", [], show_text=True)["items"][0]) == {"pkg"}


@pytest.mark.parametrize("text", ["Ваш код 123456", "1234", "code: 12345678 ok"])
def test_code_like_text_hidden_in_any_app(monkeypatch, text):
    monkeypatch.setattr(notifications.adb, "shell", lambda s, c, timeout=None: _dump("com.example.app", "Тема", text))
    assert set(notifications.scan_phone("S1", [], show_text=True)["items"][0]) == {"pkg"}


def test_long_or_short_numbers_are_not_codes():
    assert not notifications.looks_like_code("заказ 123", "12345678901")


def test_pay_matches_whole_segment_only():
    assert notifications.is_secret("com.google.android.apps.nbu.paisa.user") is False
    assert notifications.is_secret("com.example.pay.app")
    assert notifications.is_secret("ru.yoomoney.pay")
    assert not notifications.is_secret("com.example.payroll")


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
