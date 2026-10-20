"""Системные факты о телефоне для проверок сценария (блок «Если на
телефоне», шаг «Приложение готово»): версия приложения, свободное место,
интернет, заряд."""
from __future__ import annotations

import re
import shlex

from .. import adb

_VNAME = re.compile(r"versionName=(\S+)")
_VCODE = re.compile(r"versionCode=(\d+)")
_SIZE = re.compile(r"^([\d.]+)([KMGT]?)$", re.I)
# Яндекс — запасной: часть сетей режет 8.8.8.8, а интернет при этом есть.
PING = ("ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1 || "
        "ping -c 1 -W 3 77.88.8.8 >/dev/null 2>&1; echo $?")


class FactUnknown(Exception):
    """Факт не прочитался — телефон ответил не то, что ждали."""


def parse_app_version(text: str) -> dict | None:
    """Первый блок пакета: у обновлённого системного приложения ниже идёт
    «Hidden system packages» со старой версией — её не берём."""
    name, code = _VNAME.search(text or ""), _VCODE.search(text or "")
    if not name and not code:
        # «Нет» — только по прямой фразе; пустой/странный ответ — не «нет».
        if "Unable to find package" in (text or ""):
            return None
        raise FactUnknown("версия приложения")
    return {"name": name.group(1) if name else "", "code": int(code.group(1)) if code else 0}


def app_version(serial: str, package: str) -> dict | None:
    out = adb.shell(serial, ["dumpsys", "package", shlex.quote(package)], timeout=15)
    return parse_app_version(out)


def _gb(value: str) -> float | None:
    m = _SIZE.match(value or "")
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).upper()
    return n * {"": 1 / 1024 / 1024, "K": 1 / 1024 / 1024, "M": 1 / 1024,
                "G": 1, "T": 1024}[unit]


def parse_free_gb(text: str) -> float | None:
    """toybox: «1K-blocks … Available»; старый toolbox: «Size Used Free» с G/M."""
    lines = [line.split() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    head, row = lines[0], lines[-1]
    for col in ("Available", "Avail", "Free"):
        if col in head:
            i = head.index(col)
            if i >= len(row):
                return None
            value = row[i]
            if value.isdigit() and "1K-blocks" in head:
                return round(int(value) / 1024 / 1024, 2)
            return _gb(value)
    return None


def free_gb(serial: str) -> float:
    value = parse_free_gb(adb.shell(serial, ["df", "/data"], timeout=15))
    if value is None:
        raise FactUnknown("свободное место")
    return value


def battery_level(serial: str) -> int:
    level = adb.battery(serial).get("level")
    if level is None:
        raise FactUnknown("заряд")
    return int(level)


def online(serial: str) -> bool:
    lines = adb.shell(serial, PING, timeout=15).strip().splitlines()
    return bool(lines) and lines[-1].strip() == "0"


def _key(version: str) -> tuple | None:
    parts = re.findall(r"\d+", version or "")
    return tuple(int(p) for p in parts) if parts else None


def version_lt(have: str, want: str) -> bool:
    a, b = _key(have), _key(want)
    if a is None or b is None:
        raise ValueError(f"не понять версию: «{have or '?'}» и «{want or '?'}»")
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) < b + (0,) * (n - len(b))
