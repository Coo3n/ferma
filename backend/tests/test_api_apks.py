"""REST библиотеки APK. TestClient недоступен — зовём функции роутера."""
import asyncio

import pytest
from fastapi import HTTPException

import _axml
from farm import apklib, config
from farm.api import apks as api_apks


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(apklib, "usage", lambda: {"com.vkontakte.android": 3})
    return tmp_path


class Req:
    """Минимум Request для bulk._upload: заголовки и поток тела."""

    def __init__(self, data: bytes):
        self.headers = {"content-length": str(len(data))}
        self._data = data

    async def stream(self):
        yield self._data


def _upload(data, name="vk.apk"):
    return asyncio.run(api_apks.upload(Req(data), name=name))


def _vk(lib, **kw):
    args = dict(package="com.vkontakte.android", version_code=5, version_name="8.40")
    args.update(kw)
    return _axml.apk(lib / "src.apk", **args).read_bytes()


def test_загрузка_и_список(lib):
    out = _upload(_vk(lib))
    assert out["package"] == "com.vkontakte.android" and out["replaced"] is False
    rows = api_apks.list_apks()
    assert rows[0]["used"] == 3 and rows[0]["version_name"] == "8.40"


def test_не_apk_даёт_400(lib):
    with pytest.raises(HTTPException) as e:
        _upload(b"not a zip")
    assert e.value.status_code == 400 and "не архив" in e.value.detail


def test_набор_apks_пока_не_поддерживаем(lib):
    with pytest.raises(HTTPException) as e:
        _upload(b"PK...", name="vk.xapk")
    assert e.value.status_code == 400 and ".apks" in e.value.detail


def test_переименовать_и_удалить(lib):
    _upload(_vk(lib))
    assert api_apks.rename_apk("com.vkontakte.android", {"name": "ВК"})["name"] == "ВК"
    with pytest.raises(HTTPException) as e:
        api_apks.rename_apk("com.vkontakte.android", {"name": "  "})
    assert e.value.status_code == 400
    assert api_apks.delete_apk("com.vkontakte.android") == {"ok": True}
    with pytest.raises(HTTPException) as e:
        api_apks.delete_apk("com.vkontakte.android")
    assert e.value.status_code == 404
