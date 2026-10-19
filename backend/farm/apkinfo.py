"""Пакет и версия из APK без aapt: разбор бинарного AndroidManifest.xml.

Ферма работает офлайн и на Windows — тянуть build-tools ради трёх полей
незачем. Читаем только то, что нужно библиотеке APK: package, versionCode,
versionName, minSdkVersion.
"""
from __future__ import annotations

import struct
import zipfile

RES_STRING_POOL = 0x0001
RES_XML = 0x0003
RES_XML_START_ELEMENT = 0x0102
RES_XML_RESOURCE_MAP = 0x0180
UTF8_FLAG = 0x100
NO_INDEX = 0xFFFFFFFF
TYPE_STRING = 0x03
# В упакованных APK имена атрибутов в пуле часто пустые — остаётся id ресурса.
ATTR_IDS = {0x0101021B: "versionCode", 0x0101021C: "versionName",
            0x0101020C: "minSdkVersion"}


class ApkError(ValueError):
    """Файл не читается как APK; текст — для человека."""


def read(path) -> dict:
    """{package, version_code, version_name, min_sdk} из файла APK."""
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read("AndroidManifest.xml")
    except zipfile.BadZipFile:
        raise ApkError("это не APK: файл не архив") from None
    except KeyError:
        raise ApkError("это не APK: внутри нет AndroidManifest.xml") from None
    except OSError as e:
        raise ApkError(f"файл не читается: {e}") from None
    try:
        info = parse_manifest(data)
    except (struct.error, IndexError, ValueError) as e:
        if isinstance(e, ApkError):
            raise
        raise ApkError("манифест APK повреждён") from None
    if not info["package"]:
        raise ApkError("в APK не указано приложение (package)")
    return info


def parse_manifest(data: bytes) -> dict:
    kind, header, total = struct.unpack_from("<HHI", data, 0)
    if kind != RES_XML:
        raise ApkError("манифест APK не в двоичном виде")
    out = {"package": "", "version_code": 0, "version_name": "", "min_sdk": 0}
    strings: list[str] = []
    resmap: list[int] = []
    at, end = header, min(total, len(data))
    while at + 8 <= end:
        kind, head, size = struct.unpack_from("<HHI", data, at)
        if size < 8 or at + size > end:
            raise ApkError("манифест APK повреждён")
        if kind == RES_STRING_POOL:
            strings = _strings(data, at)
        elif kind == RES_XML_RESOURCE_MAP:
            n = (size - head) // 4
            resmap = list(struct.unpack_from(f"<{n}I", data, at + head))
        elif kind == RES_XML_START_ELEMENT:
            _element(data, at + head, strings, resmap, out)
        at += size
    return out


def _strings(data: bytes, at: int) -> list[str]:
    _, head, _size, count, _styles, flags, start, _ = struct.unpack_from("<HHIIIIII", data, at)
    offsets = struct.unpack_from(f"<{count}I", data, at + head)
    base = at + start
    out = []
    for off in offsets:
        p = base + off
        if flags & UTF8_FLAG:
            p += 2 if data[p] & 0x80 else 1          # длина в символах — пропускаем
            n = data[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | data[p + 1]
                p += 2
            else:
                p += 1
            out.append(data[p:p + n].decode("utf-8", "replace"))
        else:
            n = struct.unpack_from("<H", data, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            out.append(data[p:p + n * 2].decode("utf-16-le", "replace"))
    return out


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _element(data: bytes, p: int, strings: list, resmap: list, out: dict) -> None:
    _ns, name, attr_start, attr_size, count = struct.unpack_from("<IIHHH", data, p)
    tag = strings[name] if name < len(strings) else ""
    if tag not in ("manifest", "uses-sdk"):
        return
    for i in range(count):
        a = p + attr_start + i * attr_size
        _ans, aname, raw, _vsize, _res0, vtype, vdata = struct.unpack_from("<IIIHBBI", data, a)
        key = strings[aname] if aname < len(strings) else ""
        if aname < len(resmap) and resmap[aname] in ATTR_IDS:
            key = ATTR_IDS[resmap[aname]]
        if raw != NO_INDEX and raw < len(strings):
            value = strings[raw]
        elif vtype == TYPE_STRING and vdata < len(strings):
            value = strings[vdata]
        else:
            value = vdata
        if tag == "manifest" and key == "package":
            out["package"] = str(value)
        elif tag == "manifest" and key == "versionCode":
            out["version_code"] = _int(value)
        elif tag == "manifest" and key == "versionName":
            out["version_name"] = str(value)
        elif tag == "uses-sdk" and key == "minSdkVersion":
            out["min_sdk"] = _int(value)
