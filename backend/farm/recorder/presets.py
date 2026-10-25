"""Библиотека готовых скриптов конструктора.

Свой скрипт добавляется одним словарём в PRESETS:
  key    — уникальный идентификатор (латиница);
  title  — название в списке, desc — пояснение под ним;
  group  — раздел списка, один из GROUPS; keywords — слова для поиска
           (ru + en, без повторов названия): задаются таблицей _META внизу;
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

# Разделы списка готовых действий: ключ фиксирован (на него опирается фронт).
GROUPS = {
    "apps": "Приложения", "gestures": "Жесты", "feed": "Лента и видео",
    "input": "Ввод текста", "network": "Сеть", "wait": "Ожидание", "system": "Телефон",
}

PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

_PACKAGE = {"name": "package", "label": "Приложение",
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
        "desc": "Полностью закрыть приложение",
        "inputs": [_PACKAGE],
        "steps": [{"kind": "stop_app", "args": {"package": "{package}"}}],
    },
    {
        "key": "restart_app",
        "title": "Перезапустить приложение",
        "desc": "Закрыть, подождать секунду и открыть снова",
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
        "desc": "Стирает данные и вход, как после установки",
        "inputs": [_PACKAGE],
        "steps": [{"kind": "shell", "args": {"cmd": "pm clear {package}"}}],
    },
    {
        "key": "ensure_app",
        "title": "Приложение готово",
        "desc": "Проверить, что приложение стоит, и поставить из библиотеки, если нет",
        "inputs": [_PACKAGE,
                   {"name": "min_version", "label": "Версия не ниже", "hint": "любая",
                    "optional": True, "version": True}],
        "steps": [{"kind": "ensure_app",
                   "args": {"package": "{package}", "min_version": "{min_version}",
                            "install": True}}],
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
        "title": "Войти в аккаунт телефона",
        # Логин и пароль не вписываются в сценарий: на каждом телефоне берутся
        # его аккаунт из раздела «Аккаунты» (ctx.account). Вписанный пароль
        # работал бы на одном телефоне и лежал бы в файле открытым текстом.
        "desc": "Логин, Tab, пароль, Enter — из аккаунта каждого телефона "
                "(раздел «Аккаунты»). Поле логина должно быть в фокусе",
        "inputs": [{"name": "platform", "label": "Аккаунт какой соцсети",
                    "choices": {"vk": "VK", "inst": "Instagram", "tiktok": "TikTok", "tg": "Telegram"}}],
        "steps": [
            {"kind": "type", "args": {"value": "", "clear": True, "account": "{platform}", "field": "login"}},
            {"kind": "key", "args": {"name": "tab"}},
            {"kind": "type", "args": {"value": "", "clear": True, "account": "{platform}", "field": "password"}},
            {"kind": "key", "args": {"name": "enter"}},
        ],
    },
    {
        "key": "shell",
        "title": "Своя команда",
        "desc": "Для опытных: команда adb shell на телефоне",
        "inputs": [{"name": "cmd", "label": "Команда", "hint": "input keyevent 26"}],
        "steps": [{"kind": "shell", "args": {"cmd": "{cmd}"}}],
    },
    {
        "key": "double_like",
        "title": "Лайк двойным тапом",
        "desc": "Двойное касание в центре экрана — лайк в ленте и сторис",
        "inputs": [],
        "steps": [{"kind": "double_tap", "args": {"x": 0.5, "y": 0.5}}],
    },
    {
        "key": "swipe_up", "title": "Свайп вверх",
        "desc": "Провести пальцем снизу вверх — лента едет вперёд",
        "inputs": [],
        "steps": [{"kind": "swipe", "args": {"x1": 0.5, "y1": 0.75, "x2": 0.5, "y2": 0.25, "duration": 0.3}}],
    },
    {
        "key": "swipe_down", "title": "Свайп вниз",
        "desc": "Провести пальцем сверху вниз — назад по ленте",
        "inputs": [],
        "steps": [{"kind": "swipe", "args": {"x1": 0.5, "y1": 0.25, "x2": 0.5, "y2": 0.75, "duration": 0.3}}],
    },
    {
        "key": "swipe_left", "title": "Свайп влево",
        "desc": "Провести пальцем справа налево",
        "inputs": [],
        "steps": [{"kind": "swipe", "args": {"x1": 0.85, "y1": 0.5, "x2": 0.15, "y2": 0.5, "duration": 0.3}}],
    },
    {
        "key": "swipe_right", "title": "Свайп вправо",
        "desc": "Провести пальцем слева направо",
        "inputs": [],
        "steps": [{"kind": "swipe", "args": {"x1": 0.15, "y1": 0.5, "x2": 0.85, "y2": 0.5, "duration": 0.3}}],
    },
    {
        "key": "pull_refresh", "title": "Потянуть вниз — обновить ленту",
        "desc": "Медленный свайп от верха вниз, как жест «потянуть для обновления»",
        "inputs": [],
        "steps": [{"kind": "swipe", "args": {"x1": 0.5, "y1": 0.25, "x2": 0.5, "y2": 0.7, "duration": 0.6}}],
    },
    {
        "key": "tap_right_edge", "title": "Тап по правому краю — следующая история",
        "desc": "Касание у правого края экрана",
        "inputs": [],
        "steps": [{"kind": "tap", "args": {"x": 0.92, "y": 0.5}}],
    },
    {
        "key": "tap_left_edge", "title": "Тап по левому краю — назад",
        "desc": "Касание у левого края экрана",
        "inputs": [],
        "steps": [{"kind": "tap", "args": {"x": 0.08, "y": 0.5}}],
    },
    {
        "key": "scroll_feed_minutes", "title": "Листать ленту N минут",
        "desc": "Свайп вверх и случайная пауза 1–4 с, по кругу; между кругами 2–8 с",
        "inputs": [{"name": "minutes", "label": "Минуты", "hint": "10",
                    "number": True, "default": 10}],
        "steps": [
            {"kind": "loop", "args": {"span": 2, "minutes": "{minutes}",
                                      "pause_min": 2, "pause_max": 8}},
            {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.75, "x2": 0.5, "y2": 0.25, "duration": 0.3}},
            {"kind": "sleep", "args": {"seconds": 1, "seconds_max": 4}},
        ],
    },
    {
        "key": "watch_video", "title": "Смотреть видео от–до секунд",
        "desc": "Случайная пауза в заданных пределах — просмотр не одинаковый на всех телефонах",
        "inputs": [{"name": "lo", "label": "От, секунд", "hint": "5", "number": True, "default": 5},
                   {"name": "hi", "label": "До, секунд", "hint": "20", "number": True, "default": 20}],
        "steps": [{"kind": "sleep", "args": {"seconds": "{lo}", "seconds_max": "{hi}"}}],
    },
    {
        "key": "type_variants", "title": "Написать текст с вариантами",
        "desc": "Варианты в фигурных скобках через «|»: {привет|здравствуйте}, как дела? "
                "На каждом телефоне выбирается свой вариант",
        "inputs": [{"name": "text", "label": "Текст", "hint": "{привет|здравствуйте}!"}],
        "steps": [{"kind": "type", "args": {"value": "{text}"}}],
    },
    {
        "key": "clear_field", "title": "Очистить поле",
        "desc": "Стирает текст в поле, которое сейчас в фокусе",
        "inputs": [],
        "steps": [{"kind": "type", "args": {"value": "", "clear": True}}],
    },
    {
        "key": "new_ip", "title": "Сменить IP (перезапустить мобильный интернет)",
        "desc": "Выключает и включает мобильные данные: оператор выдаёт новый адрес",
        "inputs": [],
        "steps": [
            {"kind": "shell", "args": {"cmd": "svc data disable"}},
            {"kind": "sleep", "args": {"seconds": 3}},
            {"kind": "shell", "args": {"cmd": "svc data enable"}},
            {"kind": "sleep", "args": {"seconds": 6}},
        ],
    },
    {
        "key": "wifi_off", "title": "Выключить Wi-Fi", "desc": "svc wifi disable",
        "inputs": [], "steps": [{"kind": "shell", "args": {"cmd": "svc wifi disable"}}],
    },
    {
        "key": "wifi_on", "title": "Включить Wi-Fi", "desc": "svc wifi enable",
        "inputs": [], "steps": [{"kind": "shell", "args": {"cmd": "svc wifi enable"}}],
    },
    {
        "key": "airplane_on", "title": "Включить режим полёта", "desc": "Отключает всю связь",
        "inputs": [],
        "steps": [{"kind": "shell", "args": {"cmd": "cmd connectivity airplane-mode enable"}}],
    },
    {
        "key": "airplane_off", "title": "Выключить режим полёта", "desc": "Возвращает связь",
        "inputs": [],
        "steps": [{"kind": "shell", "args": {"cmd": "cmd connectivity airplane-mode disable"}}],
    },
    {
        "key": "proxy_account", "title": "Включить прокси аккаунта",
        "desc": "Прокси берётся из аккаунта телефона (раздел «Аккаунты»), формат host:port "
                "без логина — системный прокси телефона авторизацию не умеет",
        "inputs": [{"name": "platform", "label": "Аккаунт какой соцсети",
                    "choices": {"vk": "VK", "inst": "Instagram", "tiktok": "TikTok", "tg": "Telegram"}}],
        "steps": [{"kind": "proxy", "args": {"account": "{platform}"}}],
    },
    {
        "key": "proxy_off", "title": "Снять прокси", "desc": "Телефон снова ходит в сеть напрямую",
        "inputs": [], "steps": [{"kind": "proxy", "args": {"off": True}}],
    },
    {
        "key": "sleep_range", "title": "Случайная пауза от–до",
        "desc": "Каждый раз новая длительность в заданных пределах",
        "inputs": [{"name": "lo", "label": "От, секунд", "hint": "1", "number": True, "default": 1},
                   {"name": "hi", "label": "До, секунд", "hint": "4", "number": True, "default": 4}],
        "steps": [{"kind": "sleep", "args": {"seconds": "{lo}", "seconds_max": "{hi}"}}],
    },
    {
        "key": "mute", "title": "Выключить звук",
        "desc": "Громкость медиа в ноль; если команда не поддерживается — 15 нажатий «тише»",
        "inputs": [],
        "steps": [{"kind": "shell", "args": {"cmd": (
            "cmd media_session volume --stream 3 --set 0 || "
            "(for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do "
            "input keyevent KEYCODE_VOLUME_DOWN; done)")}}],
    },
    {
        "key": "screen_rotate_lock", "title": "Зафиксировать портретный режим",
        "desc": "Отключает автоповорот экрана и ставит вертикальную ориентацию",
        "inputs": [],
        "steps": [
            {"kind": "shell", "args": {"cmd": "settings put system accelerometer_rotation 0"}},
            {"kind": "shell", "args": {"cmd": "settings put system user_rotation 0"}},
        ],
    },
]

# group и keywords всех пресетов — одной таблицей: так видно раскладку по
# разделам целиком и нельзя забыть поле у нового пресета (проверяет тест).
_META = {
    "launch_app": ("apps", ["запустить", "открыть", "app", "launch", "start"]),
    "stop_app": ("apps", ["закрыть", "остановить", "kill", "force stop"]),
    "restart_app": ("apps", ["перезапуск", "заново", "restart", "reopen"]),
    "clear_app": ("apps", ["сброс", "очистить", "данные", "clear", "reset", "wipe"]),
    "ensure_app": ("apps", ["установить", "версия", "apk", "install", "update"]),
    "open_url": ("apps", ["ссылка", "браузер", "url", "link", "browser"]),
    "home": ("gestures", ["домой", "главный", "home", "desktop"]),
    "scroll_down": ("gestures", ["прокрутка", "лента", "вниз", "scroll", "feed"]),
    "scroll_up": ("gestures", ["прокрутка", "наверх", "вверх", "scroll", "top"]),
    "next_page": ("gestures", ["карусель", "галерея", "онбординг", "carousel", "next", "slide"]),
    "double_like": ("gestures", ["лайк", "сердечко", "двойной тап", "double tap", "like", "heart"]),
    "swipe_up": ("gestures", ["вверх", "swipe", "up"]),
    "swipe_down": ("gestures", ["вниз", "swipe", "down"]),
    "swipe_left": ("gestures", ["влево", "swipe", "left"]),
    "swipe_right": ("gestures", ["вправо", "swipe", "right"]),
    "pull_refresh": ("gestures", ["обновить", "потянуть", "refresh", "pull"]),
    "tap_right_edge": ("gestures", ["сторис", "история", "вперёд", "stories", "next", "right"]),
    "tap_left_edge": ("gestures", ["сторис", "история", "назад", "stories", "previous", "left"]),
    "scroll_feed_minutes": ("feed", ["листать", "лента", "прогрев", "scroll", "feed", "warmup"]),
    "watch_video": ("feed", ["просмотр", "ролик", "reels", "shorts", "watch", "video"]),
    "search_enter": ("input", ["поиск", "запрос", "search", "query", "enter"]),
    "login_fields": ("input", ["вход", "логин", "пароль", "авторизация", "login", "password", "sign in"]),
    "type_variants": ("input", ["комментарий", "уникальный", "варианты", "comment", "spin", "random text"]),
    "clear_field": ("input", ["стереть", "очистка", "clear", "erase", "delete text"]),
    "new_ip": ("network", ["ip", "адрес", "мобильные данные", "data", "reconnect", "rotate"]),
    "wifi_off": ("network", ["вайфай", "wifi", "wi-fi", "off"]),
    "wifi_on": ("network", ["вайфай", "wifi", "wi-fi", "on"]),
    "airplane_on": ("network", ["самолёт", "авиа", "airplane", "flight mode"]),
    "airplane_off": ("network", ["самолёт", "авиа", "airplane", "flight mode"]),
    "proxy_account": ("network", ["прокси", "proxy", "аккаунт"]),
    "proxy_off": ("network", ["прокси", "proxy", "отключить"]),
    "sleep": ("wait", ["подождать", "задержка", "wait", "delay", "sleep"]),
    "sleep_range": ("wait", ["случайная", "рандом", "джиттер", "random", "jitter"]),
    "screenshot": ("system", ["снимок", "экран", "screenshot", "capture"]),
    "unlock": ("system", ["разбудить", "блокировка", "экран", "wake", "unlock"]),
    "shell": ("system", ["команда", "adb", "консоль", "command", "terminal"]),
    "mute": ("system", ["звук", "громкость", "тишина", "sound", "volume", "silent"]),
    "screen_rotate_lock": ("system", ["поворот", "ориентация", "портрет", "rotation", "portrait"]),
}
for _p in PRESETS:
    _p["group"], _p["keywords"] = _META[_p["key"]]


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
