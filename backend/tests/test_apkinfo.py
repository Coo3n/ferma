"""Пакет и версия из APK без aapt."""
import zipfile

import pytest

import _axml
from farm import apkinfo

KW = dict(package="com.vkontakte.android", version_code=24015, version_name="8.40.1", min_sdk=26)


@pytest.mark.parametrize("utf8", [False, True])
@pytest.mark.parametrize("bare", [False, True])
def test_читает_пакет_и_версии(tmp_path, utf8, bare):
    path = _axml.apk(tmp_path / "vk.apk", utf8=utf8, bare_names=bare, **KW)
    assert apkinfo.read(path) == {"package": "com.vkontakte.android", "version_code": 24015,
                                  "version_name": "8.40.1", "min_sdk": 26}


def test_не_архив(tmp_path):
    path = tmp_path / "x.apk"
    path.write_bytes(b"hello")
    with pytest.raises(apkinfo.ApkError, match="не архив"):
        apkinfo.read(path)


def test_архив_без_манифеста(tmp_path):
    path = tmp_path / "x.apk"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a.txt", "x")
    with pytest.raises(apkinfo.ApkError, match="AndroidManifest"):
        apkinfo.read(path)


def test_битый_манифест(tmp_path):
    path = tmp_path / "x.apk"
    data = _axml.manifest(**KW)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", data[:40])
    with pytest.raises(apkinfo.ApkError):
        apkinfo.read(path)


def test_текстовый_манифест_не_принимаем():
    with pytest.raises(apkinfo.ApkError, match="двоичном"):
        apkinfo.parse_manifest(b"<manifest package='a.b'/>")


def test_манифест_без_package(tmp_path):
    path = _axml.apk(tmp_path / "x.apk", with_package=False, **KW)
    with pytest.raises(apkinfo.ApkError, match="не указано приложение"):
        apkinfo.read(path)


def test_битые_сжатые_данные_манифеста(tmp_path):
    path = tmp_path / "x.apk"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("AndroidManifest.xml", _axml.manifest(**KW))
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("AndroidManifest.xml")
    raw = bytearray(path.read_bytes())
    start = info.header_offset + 30 + len(info.filename)
    raw[start:start + info.compress_size] = b"\xff" * info.compress_size
    path.write_bytes(bytes(raw))
    with pytest.raises(apkinfo.ApkError, match="повреждён"):
        apkinfo.read(path)
