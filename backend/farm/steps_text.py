"""Шаги рецепта человеческими словами.

Чистый модуль, как phrases.py: ничего не знает про adb, диск и FastAPI.
Зачем: в галерее и в панели сценария человек видит, что делает сюжет, без
классов, id и координат. Неизвестный вид шага не роняет разбор — «Шаг: <вид>».
"""
from __future__ import annotations

import re

BLOCKS = ("loop", "chance", "until", "if_seen", "if_phone")

_QUOTED = re.compile(r'(?:text|description|textContains|descriptionContains)\s*=\s*"([^"]+)"')

_KEYS = {
    "BACK": "Назад",
    "HOME": "Домой",
    "ENTER": "Ввод",
    "MENU": "Меню",
    "RECENTS": "Недавние",
    "APP_SWITCH": "Недавние",
    "SEARCH": "Поиск",
    "DEL": "Удалить",
    "TAB": "Tab",
    "POWER": "Питание",
    "VOLUME_UP": "Громче",
    "VOLUME_DOWN": "Тише",
}
_ACCOUNT_FIELDS = {"login": "логин", "password": "пароль", "phone": "номер"}


def _num(value) -> str:
    """Число без лишнего «.0»; не число — как есть."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _plural(n, one: str, few: str, many: str) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return many
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    if 2 <= n % 10 <= 4:
        return few
    return many


def _args(step: dict) -> dict:
    args = step.get("args")
    return args if isinstance(args, dict) else {}


def _target(step: dict) -> str:
    """Читаемое имя цели («Нравится») из any/selector; пусто, если оно не словами."""
    candidates = []
    any_ = step.get("any")
    if isinstance(any_, list):
        candidates.extend(x for x in any_ if isinstance(x, str))
    selector = step.get("selector")
    if isinstance(selector, dict) and isinstance(selector.get("args"), str):
        candidates.append(selector["args"])
    for text in candidates:
        found = _QUOTED.search(text)
        if found:
            return found.group(1)
    return ""


def _quoted(name: str) -> str:
    return " «%s»" % name if name else ""


def _swipe(a: dict) -> str:
    try:
        dx = float(a["x2"]) - float(a["x1"])
        dy = float(a["y2"]) - float(a["y1"])
    except (KeyError, TypeError, ValueError):
        return "Провести по экрану"
    if abs(dy) >= abs(dx):
        return "Провести вниз" if dy > 0 else "Провести вверх"
    return "Провести вправо" if dx > 0 else "Провести влево"


def _click(step: dict, a: dict) -> str:
    note = step.get("note")
    if isinstance(note, str) and note.strip():
        return note.strip()
    name = _target(step)
    return "Нажать «%s»" % name if name else "Нажать на элемент"


def _type(step: dict, a: dict) -> str:
    account = a.get("account")
    if account:
        return "Ввести %s из аккаунта телефона" % _ACCOUNT_FIELDS.get(str(account), "данные")
    return "Ввести текст"


def _key(step: dict, a: dict) -> str:
    name = _KEYS.get(str(a.get("name", "")).upper().replace("KEYCODE_", ""))
    return "Нажать «%s»" % name if name else "Нажать клавишу"


def _sleep(step: dict, a: dict) -> str:
    low, high = a.get("seconds"), a.get("seconds_max")
    if low is None:
        return "Пауза"
    if high is not None and high != low:
        return "Пауза %s–%s с" % (_num(low), _num(high))
    return "Пауза %s с" % _num(low)


def _loop(step: dict, a: dict) -> str:
    if a.get("times") is not None:
        return "Повторять %s %s" % (_num(a["times"]), _plural(a["times"], "раз", "раза", "раз"))
    if a.get("minutes") is not None:
        return "Повторять %s %s" % (
            _num(a["minutes"]), _plural(a["minutes"], "минуту", "минуты", "минут"))
    return "Повторять"


def _if_seen(step: dict, a: dict) -> str:
    verb = "нет" if a.get("negate") else "есть"
    return "Если на экране %s%s:" % (verb, _quoted(_target(step)))


def _if_phone(step: dict, a: dict) -> str:
    neg = bool(a.get("negate"))
    check = a.get("check")
    if check == "battery_below":
        return "Если заряд телефона %s %s%%:" % ("не ниже" if neg else "ниже", _num(a.get("percent", "")))
    if check == "offline":
        return "Если на телефоне %s интернет:" % ("есть" if neg else "нет")
    if check == "space_below":
        return "Если свободного места %s %s ГБ:" % ("не меньше" if neg else "меньше", _num(a.get("gb", "")))
    if check == "app_installed":
        return "Если приложение %s на телефоне:" % ("не установлено" if neg else "установлено")
    if check == "app_older":
        return "Если версия приложения %s:" % ("не старее нужной" if neg else "старее нужной")
    if check == "no_account":
        return "Если аккаунт %s:" % ("привязан" if neg else "не привязан")
    return "Если на телефоне %s:" % ("не выполнено условие" if neg else "выполнено условие")


def _wait(step: dict, a: dict, word: str) -> str:
    name = _target(step)
    return "Ждать, пока %s%s" % (word, _quoted(name) if name else (" нужное" if word == "появится" else " оно"))


def _finish(step: dict, a: dict) -> str:
    if a.get("result") == "fail":
        return "Закончить сценарий с ошибкой"
    return "Закончить сценарий"


def _until(step: dict, a: dict) -> str:
    name = _target(step)
    return "Повторять, пока не появится%s" % (_quoted(name) if name else " нужное")


_PHRASES = {
    "launch_app": lambda s, a: "Открыть приложение",
    "ensure_app": lambda s, a: "Проверить, что приложение установлено",
    "stop_app": lambda s, a: "Закрыть приложение",
    "open_url": lambda s, a: "Открыть ссылку",
    "sleep": _sleep,
    "swipe": lambda s, a: _swipe(a),
    "click": _click,
    "tap": lambda s, a: "Нажать в точку экрана",
    "double_tap": lambda s, a: "Двойное нажатие",
    "long_tap": lambda s, a: "Долгое нажатие",
    "type": _type,
    "key": _key,
    "unlock": lambda s, a: "Разблокировать телефон",
    "shell": lambda s, a: "Выполнить команду",
    "screenshot": lambda s, a: "Сделать скриншот",
    "wait": lambda s, a: _wait(s, a, "появится"),
    "wait_gone": lambda s, a: _wait(s, a, "исчезнет"),
    "proxy": lambda s, a: "Выключить прокси" if a.get("off") else "Включить прокси аккаунта",
    "expect": lambda s, a: "Убедиться, что открыт экран «%s»" % a.get("name", ""),
    "branch": lambda s, a: "Развилка «%s»" % a.get("name", ""),
    "loop": _loop,
    "chance": lambda s, a: "С шансом %s%%:" % _num(a.get("percent", "")),
    "until": _until,
    "if_seen": _if_seen,
    "if_phone": _if_phone,
    "break": lambda s, a: "Выйти из повтора",
    "finish": _finish,
    "call": lambda s, a: "Запустить другой сценарий",
    "budget": lambda s, a: "Потолок за сутки: %s — %s" % (a.get("name", ""), _num(a.get("limit", ""))),
}


def _text(step) -> str:
    if not isinstance(step, dict):
        return "Шаг: ?"
    kind = step.get("kind")
    phrase = _PHRASES.get(kind) if isinstance(kind, str) else None
    if phrase is None:
        return "Шаг: %s" % (kind if kind else "?")
    try:
        return phrase(step, _args(step))
    except Exception:  # шаг со странными полями не должен ронять показ
        return "Шаг: %s" % kind


def _span(step) -> int:
    if not isinstance(step, dict) or step.get("kind") not in BLOCKS:
        return 0
    try:
        return max(0, int(_args(step).get("span", 0)))
    except (TypeError, ValueError):
        return 0


def describe(steps: list) -> list:
    """Шаги рецепта словами: [{"text", "depth"}]; depth — вложенность блоков."""
    out = []
    ends = []  # индексы (исключительно), где закрываются открытые блоки
    total = len(steps)
    for i, step in enumerate(steps):
        while ends and ends[-1] <= i:
            ends.pop()
        out.append({"text": _text(step), "depth": len(ends)})
        span = _span(step)
        if span:
            end = min(i + 1 + span, total)
            if ends:
                end = min(end, ends[-1])
            if end > i + 1:
                ends.append(end)
    return out
