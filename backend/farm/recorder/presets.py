"""Библиотека готовых скриптов конструктора.

Свой скрипт добавляется одним словарём в PRESETS:
  key    — уникальный идентификатор (латиница);
  title  — название в списке, desc — пояснение под ним;
  inputs — поля формы перед добавлением; плейсхолдер {имя} в строковых
           аргументах шагов заменяется введённым значением. Поле с
           packages=True получает автодополнение из приложений устройства,
           с number=True — числовую клавиатуру, optional=True можно
           оставить пустым;
  steps  — шаги в формате farm/recorder/steps.py (kind + args).

Опечатка в kind или аргументах не доедет до браузера:
tests/test_recorder_presets.py прогоняет каждый пресет через normalize_step.
"""
from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_PACKAGE = {"name": "package", "label": "Пакет",
            "hint": "com.android.settings", "packages": True}

PRESETS = [
    {
        "key": "launch_app",
        "title": "Открыть приложение",
        "desc": "Запустить установленное приложение",
        "inputs": [_PACKAGE],
        "steps": [{"kind": "launch_app", "args": {"package": "{package}"}}],
    },
    {
        "key": "stop_app",
        "title": "Закрыть приложение",
        "desc": "Force-stop процесса",
        "inputs": [_PACKAGE],
        "steps": [{"kind": "stop_app", "args": {"package": "{package}"}}],
    },
    {
        "key": "restart_app",
        "title": "Перезапустить приложение",
        "desc": "Force-stop, секунда паузы и запуск заново",
        "inputs": [_PACKAGE],
        "steps": [
            {"kind": "stop_app", "args": {"package": "{package}"}},
            {"kind": "sleep", "args": {"seconds": 1}},
            {"kind": "launch_app", "args": {"package": "{package}"}},
        ],
    },
    {
        "key": "clear_app",
        "title": "Сбросить данные приложения",
        "desc": "pm clear — стирает данные и кэш, как после установки",
        "inputs": [_PACKAGE],
        "steps": [{"kind": "shell", "args": {"cmd": "pm clear {package}"}}],
    },
    {
        "key": "open_url",
        "title": "Открыть ссылку",
        "desc": "URL уходит в браузер по умолчанию",
        "inputs": [{"name": "url", "label": "Ссылка", "hint": "https://example.com"}],
        "steps": [{"kind": "open_url", "args": {"url": "{url}"}}],
    },
    {
        "key": "unlock",
        "title": "Разблокировать",
        "desc": "Разбудить экран и снять блокировку",
        "inputs": [],
        "steps": [{"kind": "unlock", "args": {}}],
    },
    {
        "key": "home",
        "title": "На главный экран",
        "desc": "Клавиша «Домой»",
        "inputs": [],
        "steps": [{"kind": "key", "args": {"name": "home"}}],
    },
    {
        "key": "sleep",
        "title": "Пауза",
        "desc": "Подождать заданное число секунд",
        "inputs": [{"name": "seconds", "label": "Секунды", "hint": "1",
                    "number": True, "default": 1}],
        "steps": [{"kind": "sleep", "args": {"seconds": "{seconds}"}}],
    },
    {
        "key": "screenshot",
        "title": "Скриншот",
        "desc": "Снимок экрана в артефакты задачи",
        "inputs": [{"name": "name", "label": "Имя файла", "hint": "итог",
                    "optional": True}],
        "steps": [{"kind": "screenshot", "args": {"name": "{name}"}}],
    },
    {
        "key": "scroll_down",
        "title": "Скролл вниз ×3",
        "desc": "Три свайпа снизу вверх с паузой — прокрутить ленту",
        "inputs": [],
        "steps": [
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.78, "x2": 0.5, "y2": 0.28, "duration": 0.35}},
            {"kind": "sleep", "args": {"seconds": 0.6}},
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.78, "x2": 0.5, "y2": 0.28, "duration": 0.35}},
            {"kind": "sleep", "args": {"seconds": 0.6}},
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.78, "x2": 0.5, "y2": 0.28, "duration": 0.35}},
        ],
    },
    {
        "key": "scroll_up",
        "title": "Скролл вверх ×3",
        "desc": "Три свайпа сверху вниз — вернуться к началу ленты",
        "inputs": [],
        "steps": [
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.28, "x2": 0.5, "y2": 0.78, "duration": 0.35}},
            {"kind": "sleep", "args": {"seconds": 0.6}},
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.28, "x2": 0.5, "y2": 0.78, "duration": 0.35}},
            {"kind": "sleep", "args": {"seconds": 0.6}},
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.28, "x2": 0.5, "y2": 0.78, "duration": 0.35}},
        ],
    },
    {
        "key": "next_page",
        "title": "Следующая страница",
        "desc": "Свайп справа налево: карусель, онбординг, галерея",
        "inputs": [],
        "steps": [{"kind": "swipe", "args": {"x1": 0.85, "y1": 0.5, "x2": 0.15, "y2": 0.5, "duration": 0.3}}],
    },
    {
        "key": "search_enter",
        "title": "Поиск: ввести и нажать Enter",
        "desc": "Печатает запрос в поле, которое сейчас в фокусе, и отправляет",
        "inputs": [{"name": "query", "label": "Запрос", "hint": "кроссовки"}],
        "steps": [
            {"kind": "type", "args": {"value": "{query}", "clear": True}},
            {"kind": "key", "args": {"name": "enter"}},
        ],
    },
    {
        "key": "login_fields",
        "title": "Авторизация: логин и пароль",
        "desc": "Логин, Tab, пароль, Enter — поле логина должно быть в фокусе. "
                "Значения потом выносятся в параметры кнопкой {}",
        "inputs": [{"name": "login", "label": "Логин", "hint": "user@example.com"},
                   {"name": "password", "label": "Пароль", "hint": "••••••"}],
        "steps": [
            {"kind": "type", "args": {"value": "{login}", "clear": True}},
            {"kind": "key", "args": {"name": "tab"}},
            {"kind": "type", "args": {"value": "{password}", "clear": True}},
            {"kind": "key", "args": {"name": "enter"}},
        ],
    },
    {
        "key": "shell",
        "title": "Команда adb shell",
        "desc": "Произвольная команда на устройстве",
        "inputs": [{"name": "cmd", "label": "Команда", "hint": "input keyevent 26"}],
        "steps": [{"kind": "shell", "args": {"cmd": "{cmd}"}}],
    },
]


def fill(preset: dict, values: dict) -> list:
    """Шаги пресета с подставленными значениями формы.

    Ту же замену делает браузер (recFill в frontend/js/recorder.js) — здесь она
    нужна тестам, чтобы каждый пресет проверялся через normalize_step.
    """
    out = []
    for step in preset["steps"]:
        args = {}
        for name, value in step["args"].items():
            if isinstance(value, str):
                value = PLACEHOLDER_RE.sub(
                    lambda m: str(values.get(m.group(1), "")), value)
            args[name] = value
        out.append({"kind": step["kind"], "args": args})
    return out
