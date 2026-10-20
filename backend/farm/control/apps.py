"""Приложения: запуск, остановка, установка, права."""
from __future__ import annotations

import re
import shlex
import time

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
# «* Recent #1: Task{5d3c76b #29 type=standard A=10164:com.mi.appfinder}» или
# «… I=com.vkontakte.android/.MainActivity}» — номер задачи, вид и пакет.
_RECENT_TASK = re.compile(
    r"\* Recent #\d+: Task\{\w+ #(\d+) type=(\w+)\s+(?:A=(?:\d+:)?([\w.]+)|I=([\w.]+)/)")
_ROOT_TASK = re.compile(r"rootTaskId=(\d+)")

# Какие пакеты — «приложения» (со значком): список меняется редко, а
# dumpsys на каждое открытие вкладки «Открытые» — лишняя секунда.
LAUNCHABLE_TTL = 120.0
_launchable: dict[str, tuple[float, set[str]]] = {}


def _launchable_set(serial: str) -> set[str]:
    hit = _launchable.get(serial)
    if hit and time.monotonic() - hit[0] < LAUNCHABLE_TTL:
        return hit[1]
    pkgs = set(adb.visible_packages(serial))
    _launchable[serial] = (time.monotonic(), pkgs)
    return pkgs


def recent_tasks(serial: str) -> list[dict]:
    """Задачи из «Недавних», свежие первыми: [{package, task, root}].

    Только обычные приложения (type=standard) — без рабочего стола и
    служебных окон; один пакет — одна запись (его задачи вместе).
    """
    out = adb.shell(serial, ["dumpsys", "activity", "recents"], timeout=15)
    tasks: dict[str, dict] = {}
    blocks = re.split(r"(?=\* Recent #)", out)
    for block in blocks:
        m = _RECENT_TASK.search(block)
        if not m or m.group(2) != "standard":
            continue
        pkg = m.group(3) or m.group(4)
        if not pkg or _KEEP_OPEN.search(pkg):
            continue
        root = _ROOT_TASK.search(block)
        entry = tasks.setdefault(pkg, {"package": pkg, "tasks": []})
        entry["tasks"].append(int(root.group(1)) if root else int(m.group(1)))
    return list(tasks.values())


def recent_packages(serial: str) -> list[str]:
    """Пакеты из «Недавних» (бэкстек), свежие первыми, без дублей. Только
    приложения со значком: служебное вроде поиска MIUI (com.mi.appfinder)
    человек «открытым» не считает и не узнаёт по имени."""
    launchable = _launchable_set(serial)
    return [t["package"] for t in recent_tasks(serial) if not launchable or t["package"] in launchable]


def close_recent(serial: str, package: str) -> None:
    """Закрыть приложение и убрать его из «Недавних». Одного force-stop мало:
    задача оставалась в списке, и «закрытое» появлялось там снова."""
    stop_app(serial, package)
    for entry in recent_tasks(serial):
        if entry["package"] != package:
            continue
        for task in entry["tasks"]:
            try:
                adb.shell(serial, ["am", "stack", "remove", str(task)], timeout=10)
            except adb.AdbError:
                pass   # старые прошивки без «stack remove» — хватит и force-stop


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
