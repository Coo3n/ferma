"""Маленькие APK для тестов: zip с бинарным AndroidManifest.xml.

Пишется ровно то, что читает farm/apkinfo.py: пул строк, карта ресурсов,
начало <manifest> и <uses-sdk>. bare_names=True — имена атрибутов в пуле
пустые, как в упакованных R8/aapt2 APK: остаются только id ресурсов.
"""
import struct
import zipfile
from pathlib import Path

NO = 0xFFFFFFFF
# Порядок важен: первые три строки — имена атрибутов, их id в карте ресурсов.
_IDS = [0x0101021B, 0x0101021C, 0x0101020C]


def _pool(strings, utf8):
    data, offsets = b"", []
    for s in strings:
        offsets.append(len(data))
        if utf8:
            raw = s.encode("utf-8")
            data += bytes([len(s), len(raw)]) + raw + b"\0"
        else:
            data += struct.pack("<H", len(s)) + s.encode("utf-16-le") + b"\0\0"
    while len(data) % 4:
        data += b"\0"
    header = 28
    body = struct.pack(f"<{len(strings)}I", *offsets) + data
    return struct.pack("<HHIIIIII", 0x0001, header, header + len(body), len(strings), 0,
                       0x100 if utf8 else 0, header + 4 * len(strings), 0) + body


def _resmap():
    body = struct.pack(f"<{len(_IDS)}I", *_IDS)
    return struct.pack("<HHI", 0x0180, 8, 8 + len(body)) + body


def _attr(name, *, string=None, number=None):
    if string is not None:
        return struct.pack("<IIIHBBI", NO, name, string, 8, 0, 0x03, string)
    return struct.pack("<IIIHBBI", NO, name, NO, 8, 0, 0x10, number)


def _start(tag, attrs):
    ext = struct.pack("<IIHHHHHH", NO, tag, 20, 20, len(attrs), 0, 0, 0)
    body = ext + b"".join(attrs)
    return struct.pack("<HHIII", 0x0102, 16, 16 + len(body), 1, NO) + body


def manifest(package, version_code, version_name, min_sdk=21, utf8=False, bare_names=False,
             with_package=True):
    names = ["", "", ""] if bare_names else ["versionCode", "versionName", "minSdkVersion"]
    strings = names + ["package", "manifest", "uses-sdk", package, version_name]
    body = (_pool(strings, utf8) + _resmap()
            + _start(4, [*([_attr(3, string=6)] if with_package else []),
                         _attr(0, number=version_code), _attr(1, string=7)])
            + _start(5, [_attr(2, number=min_sdk)]))
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def apk(path, **kw) -> Path:
    path = Path(path)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("AndroidManifest.xml", manifest(**kw))
        z.writestr("classes.dex", b"dex\n035\0")
    return path
