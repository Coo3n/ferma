"""Приложения: запуск, остановка, установка, права."""
from __future__ import annotations

import re
import shlex

from .. import adb
from .fallback import from_u2, via_u2

INSTALL_TIMEOUT = 300
UNINSTALL_TIMEOUT = 60


def launch_app(serial: str, package: str, activity: str | None = None,
               stop_first: bool = False) -> None:
    if stop_first:
        stop_app(serial, package)
    if activity:
        component = package + "/" + activity
        adb.shell(serial, ["am", "start", "-n", shlex.quote(component)])
        return
    if via_u2(serial, lambda d: d.app_start(package)):
        return
    adb.shell(serial, ["monkey", "-p", shlex.quote(package),
                       "-c", "android.intent.category.LAUNCHER", "1"])


def stop_app(serial: str, package: str) -> None:
    adb.shell(serial, ["am", "force-stop", shlex.quote(package)])


# Оболочка и лаунчер не закрываем: после этого экран пустой, а не «чистый».
_KEEP_OPEN = re.compile(r"systemui|launcher|\.miui\.home$|\.home$")
_RECENT_CMP = re.compile(r"(?:cmp|realActivity)=([\w.]+)/")


def recent_packages(serial: str) -> list[str]:
    """Пакеты из «последних» (бэкстек), свежие первыми, без дублей."""
    out = adb.shell(serial, ["dumpsys", "activity", "recents"], timeout=15)
    seen: dict[str, None] = {}
    for pkg in _RECENT_CMP.findall(out):
        if not _KEEP_OPEN.search(pkg):
            seen.setdefault(pkg)
    return list(seen)


def open_url(serial: str, url: str) -> None:
    # Аргументы склеиваются и уходят в sh телефона: без кавычек `&` в ссылке
    # обрезал бы её и запускал остаток как команду.
    adb.shell(serial, ["am", "start", "-a", "android.intent.action.VIEW", "-d", shlex.quote(url)])


def install(serial: str, apk_path: str, grant_permissions: bool = True,
            reinstall: bool = True) -> str:
    args = ["install"]
    if reinstall:
        args.append("-r")
    if grant_permissions:
        args.append("-g")
    args.append(apk_path)
    return adb.raw(args, serial=serial, timeout=INSTALL_TIMEOUT)


def uninstall(serial: str, package: str) -> str:
    return adb.raw(["uninstall", package], serial=serial, timeout=UNINSTALL_TIMEOUT)


def grant(serial: str, package: str, permission: str) -> None:
    if "." not in permission:
        permission = "android.permission." + permission.upper()
    adb.shell(serial, ["pm", "grant", shlex.quote(package), shlex.quote(permission)])


def current_app(serial: str) -> str:
    current = from_u2(serial, lambda d: d.app_current().get("package", ""))
    if current is not None:
        return current
    return adb.current_app(serial)
