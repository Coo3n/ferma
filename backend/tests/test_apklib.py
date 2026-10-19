"""Библиотека APK: файлы, индекс, установка под семафором."""
import threading
import time

import pytest

import _axml
from farm import apkinfo, apklib, config


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    return tmp_path


def _apk(tmp_path, name="vk.apk", **kw):
    args = dict(package="com.vkontakte.android", version_code=1, version_name="8.40")
    args.update(kw)
    return _axml.apk(tmp_path / name, **args)


def test_добавить_и_прочитать(lib):
    out = apklib.add(_apk(lib))
    assert out["package"] == "com.vkontakte.android"
    assert out["name"] == "VK" and out["version_name"] == "8.40" and out["replaced"] is False
    assert (lib / "data" / "apks" / "com.vkontakte.android.apk").is_file()
    assert apklib.get("com.vkontakte.android")["size"] > 0
    assert [a["package"] for a in apklib.list_all()] == ["com.vkontakte.android"]


def test_новый_apk_заменяет_старый_и_хранит_имя(lib):
    apklib.add(_apk(lib))
    apklib.rename("com.vkontakte.android", "ВК рабочий")
    out = apklib.add(_apk(lib, name="vk2.apk", version_code=2, version_name="8.41"))
    assert out["replaced"] is True and out["name"] == "ВК рабочий"
    assert apklib.get("com.vkontakte.android")["version_name"] == "8.41"
    assert len(apklib.list_all()) == 1


def test_битый_файл_не_попадает_в_библиотеку(lib):
    bad = lib / "x.apk"
    bad.write_bytes(b"nope")
    with pytest.raises(apkinfo.ApkError):
        apklib.add(bad)
    assert apklib.list_all() == []


def test_имя_по_пакету(lib):
    assert apklib.name_of("org.telegram.messenger") == "Telegram"
    assert apklib.name_of("com.example.superapp") == "Superapp"


def test_удалить(lib):
    apklib.add(_apk(lib))
    assert apklib.remove("com.vkontakte.android") is True
    assert apklib.get("com.vkontakte.android") is None
    assert not (lib / "data" / "apks" / "com.vkontakte.android.apk").exists()
    assert apklib.remove("com.vkontakte.android") is False


def test_счётчик_использования(lib, monkeypatch):
    from farm import scenarios
    from farm.recorder import save

    class Sc:
        def __init__(self, key):
            self.key = key

    recipes = {
        "a": {"steps": [{"kind": "ensure_app", "args": {"package": "com.vk"}},
                        {"kind": "if_phone", "args": {"check": "app_installed", "package": "com.vk"}}]},
        "b": {"steps": [{"kind": "if_phone", "args": {"check": "offline"}}]},
        "c": None,
    }
    monkeypatch.setattr(scenarios, "discover", lambda force=False: [Sc(k) for k in recipes])
    monkeypatch.setattr(save, "load_recipe", lambda key: recipes[key])
    assert apklib.usage() == {"com.vk": 1}


def test_установка_ставит_файл_из_библиотеки(lib, monkeypatch):
    apklib.add(_apk(lib))
    calls = []
    monkeypatch.setattr(apklib.control, "install", lambda s, p: calls.append((s, p)) or "Success")
    assert apklib.install("S1", "com.vkontakte.android") == "Success"
    assert calls[0][0] == "S1" and calls[0][1].endswith("com.vkontakte.android.apk")


def test_причина_отказа_словами(lib, monkeypatch):
    apklib.add(_apk(lib))
    monkeypatch.setattr(apklib.control, "install",
                        lambda s, p: "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]")
    with pytest.raises(apklib.InstallFailed, match="места"):
        apklib.install("S1", "com.vkontakte.android")


def test_нет_в_библиотеке(lib):
    with pytest.raises(apklib.InstallFailed, match="нет в библиотеке"):
        apklib.install("S1", "com.nope")


def test_не_больше_четырёх_установок_разом(lib, monkeypatch):
    apklib.add(_apk(lib))
    now, peak, lock = [0], [0], threading.Lock()

    def slow(serial, path):
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        time.sleep(0.05)
        with lock:
            now[0] -= 1
        return "Success"

    monkeypatch.setattr(apklib.control, "install", slow)
    threads = [threading.Thread(target=apklib.install, args=(f"S{i}", "com.vkontakte.android"))
               for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 4


def test_отмена_в_очереди(lib, monkeypatch):
    apklib.add(_apk(lib))
    for _ in range(4):
        apklib.SLOTS.acquire()
    try:
        class Stop(Exception):
            pass

        def cancel():
            raise Stop

        with pytest.raises(Stop):
            apklib.install("S1", "com.vkontakte.android", check_cancel=cancel)
    finally:
        for _ in range(4):
            apklib.SLOTS.release()


def test_странное_имя_пакета_это_ApkError(lib):
    bad = _apk(lib, name="odd.apk", package="x")
    with pytest.raises(apkinfo.ApkError) as e:
        apklib.add(bad)
    assert "имя приложения" in str(e.value)
    assert apklib.list_all() == []


def test_сбой_копирования_не_оставляет_part(lib, monkeypatch):
    import shutil

    def boom(src, dst, *a, **k):
        with open(dst, "wb") as fh:
            fh.write(b"half")
        raise OSError("диск полон")
    monkeypatch.setattr(shutil, "copyfile", boom)
    with pytest.raises(OSError):
        apklib.add(_apk(lib))
    assert list((lib / "data" / "apks").glob("*.part")) == []
    assert apklib.list_all() == []


def test_параллельное_добавление_одного_пакета(lib):
    a = _apk(lib, name="a.apk", version_code=1, version_name="1")
    b = _apk(lib, name="b.apk", version_code=2, version_name="2")
    errs = []

    def run(p):
        try:
            for _ in range(10):
                apklib.add(p)
        except Exception as e:  # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=run, args=(p,)) for p in (a, b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errs == []
    row = apklib.get("com.vkontakte.android")
    stored = lib / "data" / "apks" / "com.vkontakte.android.apk"
    assert apklib._sha256(stored) == row["sha256"]
    assert list(stored.parent.glob("*.part")) == []


def test_переименовать_неизвестное_и_пустое(lib):
    assert apklib.rename("com.nope.app", "Имя") is None
    apklib.add(_apk(lib))
    assert apklib.rename("com.vkontakte.android", "  ") is None
    assert apklib.get("com.vkontakte.android")["name"] == "VK"


def test_битый_индекс_сохраняется_копией(lib, caplog):
    idx = lib / "data" / "apks.json"
    idx.parent.mkdir(parents=True)
    idx.write_text("{не json", "utf-8")
    with caplog.at_level("WARNING", logger="farm.apklib"):
        apklib.add(_apk(lib))
    assert (lib / "data" / "apks.json.bad").read_text("utf-8") == "{не json"
    assert any("apks.json" in r.getMessage() for r in caplog.records)
