"""«Открытые» в пульте: только приложения со значком, закрытие убирает задачу
из «Недавних» (одного force-stop мало — приложение оставалось в списке)."""
from farm.control import apps

DUMP = """ACTIVITY MANAGER RECENT TASKS (dumpsys activity recents)
  * Recent #0: Task{bdab5a8 #2 type=home I=com.mi.android.globallauncher/com.miui.home.launcher.Launcher}
    taskId=2 rootTaskId=1
  * Recent #1: Task{1111111 #41 type=standard I=com.vkontakte.android/.MainActivity}
    taskId=41 rootTaskId=41
  * Recent #2: Task{5d3c76b #29 type=standard A=10164:com.mi.appfinder}
    taskId=29 rootTaskId=29
  * Recent #3: Task{2222222 #35 type=standard A=10200:org.telegram.messenger}
    taskId=35 rootTaskId=35
"""


def _fake(monkeypatch, calls):
    def shell(serial, args, timeout=None):
        calls.append(args)
        return DUMP if args[:2] == ["dumpsys", "activity"] else ""
    monkeypatch.setattr(apps.adb, "shell", shell)
    monkeypatch.setattr(apps.adb, "visible_packages",
                        lambda serial: ["com.vkontakte.android", "org.telegram.messenger"])
    apps._launchable.clear()


def test_recent_packages_skip_home_and_service_tasks(monkeypatch):
    _fake(monkeypatch, [])
    assert apps.recent_packages("X") == ["com.vkontakte.android", "org.telegram.messenger"]


def test_close_recent_stops_and_removes_task(monkeypatch):
    calls = []
    _fake(monkeypatch, calls)
    apps.close_recent("X", "com.vkontakte.android")
    assert ["am", "force-stop", "com.vkontakte.android"] in calls
    assert ["am", "stack", "remove", "41"] in calls
    assert ["am", "stack", "remove", "35"] not in calls
