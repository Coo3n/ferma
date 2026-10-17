"""Схема данных, приходящих из конструктора в браузере.

Модуль намеренно не знает ни про adb, ни про FastAPI, ни про файловую систему:
на входе словари из JSON, на выходе они же, но проверенные. Это условие
тестируемости — то же, что у farm/ui/tree.py (см. docs/GOTCHAS.md).
"""
from __future__ import annotations

import ast
import math
import re

PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# kind -> (обязательные аргументы, необязательные)
ARGS = {
    "click": ((), ()),
    "tap": (("x", "y"), ()),
    "long_tap": (("x", "y"), ("duration",)),
    "swipe": (("x1", "y1", "x2", "y2"), ("duration",)),
    "type": (("value",), ("clear", "account", "field")),
    "key": (("name",), ()),
    "unlock": ((), ()),
    "launch_app": (("package",), ()),
    "open_url": (("url",), ()),
    "stop_app": (("package",), ()),
    "shell": (("cmd",), ()),
    "sleep": (("seconds",), ()),
    "screenshot": ((), ("name",)),
    "expect": (("name",), ()),
    "branch": (("name",), ("timeout",)),
}

NUMERIC = {"x", "y", "x1", "y1", "x2", "y2", "duration", "seconds", "timeout"}
BOOLEAN = {"clear"}

# Шаги, чьё значение можно вынести в PARAMS. Селекторы сюда не входят:
# они хранятся готовой строкой из farm/ui/selectors.py и не разбираются.
PARAMETRIZABLE = {"type", "launch_app", "open_url", "stop_app", "shell", "sleep",
                  "screenshot"}


# Шаги, которым допустимы «пропустить при неудаче» и «повторить». Проверки
# экрана (expect/branch) и sleep сюда не входят: у них своя логика ожидания.
FLEXIBLE = {"click", "tap", "long_tap", "swipe", "type", "key", "launch_app",
            "open_url", "stop_app", "shell", "screenshot", "unlock"}
RETRIES_MAX = 5

_LABELS = {
    "click": "Тап по элементу", "tap": "Тап", "long_tap": "Долгое нажатие",
    "swipe": "Свайп", "type": "Ввод текста", "key": "Клавиша",
    "unlock": "Разблокировать", "launch_app": "Запуск приложения",
    "stop_app": "Остановка приложения", "open_url": "Открыть ссылку",
    "shell": "Команда shell", "sleep": "Пауза", "screenshot": "Скриншот",
    "expect": "Якорь экрана", "branch": "Развилка",
}


def label_of(step: dict) -> str:
    """Короткая подпись шага для прогресса и отчётов."""
    kind, args = step.get("kind"), step.get("args") or {}
    base = _LABELS.get(kind, str(kind))
    tail = ""
    if kind in ("expect", "branch"):
        tail = args.get("name", "")
    elif kind in ("launch_app", "stop_app"):
        tail = args.get("package", "")
    elif kind == "type":
        tail = (f'{ACCOUNT_FIELDS.get(args.get("field"), "")} {args["account"]}'
                if args.get("account") else args.get("value", ""))
    elif kind == "key":
        tail = args.get("name", "")
    elif kind == "click":
        m = re.search(r'(?:text|description|resourceId)\w*="([^"]{1,40})"',
                      ((step.get("selector") or {}).get("args") or ""))
        tail = m.group(1) if m else ""
    note = step.get("note")
    text = f"{base}: {tail}" if tail else base
    return f"{text} — {note}" if note else text


class StepError(ValueError):
    """Данные конструктора не проходят проверку — запрос отвергается с 400."""


def _text(value) -> str:
    """Однострочная строка: переводы строк ломают и комментарий, и метку."""
    return " ".join(str(value or "").split())


# Сколько запасных селекторов пишется в шаг: дальше третьего кандидата идут
# только хрупкие варианты вида className+instance, они цепочку не улучшают.
MAX_FALLBACKS = 3

# Запасные слои резолвера у шага click. Кроп — только имя файла внутри папки
# ассетов сценария: слеши и ведущие точки закрыты регуляркой.
TEXTS_MAX = 3
CROP_RE = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,60}\.png$")


def _texts(kind: str, raw) -> list:
    if raw in (None, []):
        return []
    if kind != "click":
        raise StepError(f"поле texts допустимо только у click, не у {kind}")
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raise StepError("texts — список строк")
    out, seen = [], set()
    for item in raw:
        item = _text(item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out[:TEXTS_MAX]


def _crop(kind: str, raw):
    if raw in (None, ""):
        return None
    if kind != "click":
        raise StepError(f"поле crop допустимо только у click, не у {kind}")
    if not isinstance(raw, str) or not CROP_RE.match(raw):
        raise StepError("crop: имя png-файла из латиницы, цифр, _ . -")
    return raw


def _point(kind: str, raw):
    if raw in (None, []):
        return None
    if kind != "click":
        raise StepError(f"поле point допустимо только у click, не у {kind}")
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise StepError("point — пара чисел [x, y]")
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise StepError("point: нормализованные координаты 0..1")
    return [round(x, 4), round(y, 4)]


def _pos(raw):
    """Позиция карточки шага на холсте схемы — пиксели, любой знак.

    В отличие от point у click (доля экрана 0..1), это координата на
    холсте конструктора, а не на экране устройства — диапазон не
    ограничен: холст можно прокрутить в любую сторону.
    """
    if raw in (None, []):
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise StepError("pos — пара чисел [x, y]")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise StepError("pos: числа должны быть конечными")
    return [round(x), round(y)]


ANY_MAX = 3


def _features(raw, чей: str) -> list:
    """Признаки экрана: строки аргументов u2-селекторов, «любой из».

    Общее для якоря и для ветви развилки: и тот и другая отвечают на вопрос
    «этот ли экран передо мной», и описываются одинаково.
    """
    if (not isinstance(raw, list)
            or not all(isinstance(s, str) and s.strip() for s in raw)):
        raise StepError(f"{чей} — непустой список строк-селекторов")
    seen, out = set(), []
    for item in raw:
        # строка уходит в .py дословно (`dict(<item>)`) — той же грамматикой,
        # что и селектор клика; без этого новая строка в признаке = код на хосте
        _check_kwargs(item, чей)
        if item not in seen:
            seen.add(item)
            out.append(item)
    if not out:
        raise StepError(f"{чей} — непустой список строк-селекторов")
    return out[:ANY_MAX]


def _anchor(kind: str, raw):
    """Признаки экрана у шага expect: строки аргументов u2-селекторов."""
    if raw in (None, []):
        if kind == "expect":
            raise StepError("шагу expect нужен хотя бы один признак экрана")
        return None
    if kind != "expect":
        raise StepError(f"поле any допустимо только у expect, не у {kind}")
    return _features(raw, "any")


# Ветвление: «если на экране X — выполни блок Y». Ветвей больше пяти в одной
# развилке не бывает читаемо: дальше это не сюжет, а таблица переходов, и её
# место в отдельных сценариях.
ARMS_MAX = 5

# Ключ блока. Повторяет KEY_RE из recorder/save.py сознательно: steps.py не
# знает ни про файловую систему, ни про то, где лежат сценарии, — это условие
# его тестируемости. Проверка здесь не про безопасность (ключ уезжает в код
# строковым литералом), а про то, чтобы опечатка ловилась при сохранении, а не
# на прогоне через полчаса.
RUN_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def _arms(kind: str, raw):
    """Ветви развилки: имя, признаки экрана и блок, который на ней выполнить.

    Блок может быть пустым: «этот экран нам знаком, делать на нём ничего не
    надо» — тоже ветка, и объявлять её полезно, иначе развилка будет писать
    отклонение на каждом нормальном прогоне.
    """
    if kind != "branch":
        if raw:
            raise StepError(f"поле arms допустимо только у branch, не у {kind}")
        return None
    if not isinstance(raw, list) or not raw:
        raise StepError("шагу branch нужна хотя бы одна ветка")
    out, имена = [], set()
    for item in raw[:ARMS_MAX]:
        if not isinstance(item, dict):
            raise StepError("ветка должна быть объектом")
        name = _text(item.get("name"))
        if not name:
            raise StepError("у ветки нет имени")
        if name in имена:
            raise StepError(f"две ветки с именем «{name}»: "
                            f"по имени выбирается блок, имена обязаны различаться")
        имена.add(name)
        run = _text(item.get("run"))
        if run and not RUN_RE.match(run):
            raise StepError(f"блок ветки «{name}»: латиница в нижнем регистре, "
                            f"цифры и _, начиная с буквы")
        out.append({"name": name,
                    "any": _features(item.get("any"), f"признаки ветки «{name}»"),
                    "run": run})
    return out


def _check_kwargs(args, what: str) -> str:
    """Аргументы селектора — только `ключ=значение` через запятую.

    Кодоген вставляет строку в .py дословно (`ctx.click(<args>)`), а файл
    исполняется на хосте фермы при следующем discover. Поэтому принимаем ровно
    то, что генерирует панель (farm/ui/selectors.py): именованные аргументы со
    значениями — строка, int, True/False. Разбор через ast, без eval; сверх
    этого запрещены любые управляющие символы, в том числе перевод строки, за
    которым в скобках мог бы спрятаться посторонний код.
    """
    if not isinstance(args, str) or not args.strip():
        raise StepError(f"{what}: нужна непустая строка")
    if any(ord(c) < 32 or ord(c) == 127 for c in args):
        raise StepError(f"{what}: управляющие символы и переводы строк недопустимы")
    bad = StepError(f"{what}: допустимы только пары ключ=значение "
                    "(строка в кавычках, число или True/False)")
    try:
        tree = ast.parse(f"f({args})", mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise bad
    call = tree.body
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            and call.func.id == "f" and not call.args and call.keywords):
        raise bad
    for kw in call.keywords:
        v = kw.value
        if kw.arg is None or not isinstance(v, ast.Constant) \
                or type(v.value) not in (str, int, bool):
            raise bad
    return args


def _selector(kind: str, raw) -> dict | None:
    if kind != "click":
        return None
    if not isinstance(raw, dict):
        raise StepError("шаг click без селектора")
    call, args = raw.get("call"), raw.get("args")
    if call != "click" or not isinstance(args, str) or not args.strip():
        raise StepError("селектор шага click должен быть вызовом click с аргументами")
    _check_kwargs(args, "селектор")

    seen, extra = {args}, []
    for item in (raw.get("fallbacks") or []):
        if not isinstance(item, str) or not item.strip():
            raise StepError("запасной селектор должен быть непустой строкой")
        _check_kwargs(item, "запасной селектор")
        if item in seen:
            continue
        seen.add(item)
        extra.append(item)
    return {"call": "click", "args": args, "fallbacks": extra[:MAX_FALLBACKS]}


def _param(kind: str, raw) -> str | None:
    if raw in (None, ""):
        return None
    if kind not in PARAMETRIZABLE:
        raise StepError(f"шаг {kind} нельзя параметризовать")
    if not isinstance(raw, str) or not PARAM_NAME_RE.match(raw):
        raise StepError(f"имя параметра «{raw}»: латиница в нижнем регистре, цифры и _")
    return raw


def _args(kind: str, raw) -> dict:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise StepError(f"аргументы шага {kind} должны быть объектом")
    required, optional = ARGS[kind]
    out = {}
    for name in required + optional:
        if name not in raw:
            if name in required:
                raise StepError(f"шагу {kind} не хватает аргумента «{name}»")
            continue
        value = raw[name]
        if name in NUMERIC:
            try:
                value = float(value)
            except (TypeError, ValueError, OverflowError):
                raise StepError(f"аргумент «{name}» шага {kind} должен быть числом")
            if not math.isfinite(value):
                # nan/inf кодоген написал бы голым именем — NameError на прогоне
                raise StepError(f"аргумент «{name}» шага {kind} должен быть конечным числом")
        elif name in BOOLEAN:
            value = bool(value)
        else:
            value = str(value)
        out[name] = value
    return out


# Ввод из «Аккаунтов»: сценарий берёт логин/пароль телефона, на котором идёт,
# а не зашитый в код — один сценарий на все 40 телефонов.
ACCOUNT_FIELDS = {"login": "логин", "password": "пароль", "phone": "телефон"}


def _check_account(kind: str, args: dict) -> None:
    if kind != "type" or not (args.get("account") or args.get("field")):
        args.pop("account", None)
        args.pop("field", None)
        return
    from ..accounts import PLATFORMS
    if args.get("account") not in PLATFORMS:
        raise StepError(f"аккаунт: платформа одна из {', '.join(PLATFORMS)}")
    if args.get("field") not in ACCOUNT_FIELDS:
        raise StepError("аккаунт: поле login, password или phone")


def normalize_step(raw) -> dict:
    """Проверенный шаг ровно с ключами kind, args, selector, param, note,
    texts, crop, point, any, arms, report, pos. texts/crop/point — запасные
    слои резолвера цели у click, arms и report — только у branch, pos —
    позиция карточки на холсте «Схемы», не участвует в генерации кода."""
    if not isinstance(raw, dict):
        raise StepError("шаг должен быть объектом")
    kind = raw.get("kind")
    if kind not in ARGS:
        raise StepError(f"неизвестный шаг: {kind!r}")
    step = {
        "kind": kind,
        "args": _args(kind, raw.get("args")),
        "selector": _selector(kind, raw.get("selector")),
        "param": _param(kind, raw.get("param")),
        "note": _text(raw.get("note")),
        "texts": _texts(kind, raw.get("texts")),
        "crop": _crop(kind, raw.get("crop")),
        "point": _point(kind, raw.get("point")),
        "any": _anchor(kind, raw.get("any")),
        "arms": _arms(kind, raw.get("arms")),
        # Жаловаться ли, когда ни одна ветка не совпала. По умолчанию да:
        # молчащая развилка прячет появившуюся ветку до первого падения
        # где-то дальше по сценарию.
        "report": bool(raw.get("report", True)) if kind == "branch" else None,
        "pos": _pos(raw.get("pos")),
        # Необязательный шаг: неудача не роняет сценарий; retries — сколько
        # раз повторить до сдачи. Только у FLEXIBLE, иначе ключи None.
    }
    # Ключи появляются только когда заданы: рецепты и тесты без них не меняются.
    if _flag(kind, raw.get("optional")):
        step["optional"] = True
    retries = _retries(kind, raw.get("retries"))
    if retries:
        step["retries"] = retries
    _check_account(kind, step["args"])
    if step["args"].get("account"):
        step["param"] = None   # аккаунт и параметр — два источника одного значения
    return step


def _flag(kind: str, raw):
    if not raw:
        return None
    if kind not in FLEXIBLE:
        raise StepError(f"шаг {kind} нельзя сделать необязательным")
    return True


def _retries(kind: str, raw):
    if raw in (None, "", 0, False):
        return None
    if kind not in FLEXIBLE:
        raise StepError(f"шаг {kind} нельзя повторять")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise StepError("retries — целое число")
    if not 1 <= n <= RETRIES_MAX:
        raise StepError(f"retries: от 1 до {RETRIES_MAX}")
    return n


def normalize_steps(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StepError("шаги должны быть списком")
    return [normalize_step(item) for item in raw]


def normalize_meta(raw) -> dict:
    if not isinstance(raw, dict):
        raise StepError("не заданы название и описание")
    name = _text(raw.get("name"))
    if not name:
        raise StepError("не задано название сценария")
    return {
        "name": name,
        "description": _text(raw.get("description")),
        "watch_popups": bool(raw.get("watch_popups", True)),
        "human": bool(raw.get("human", True)),
    }


def normalize_params(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise StepError("параметры должны быть объектом")
    out = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not PARAM_NAME_RE.match(name):
            raise StepError(f"имя параметра «{name}»: латиница в нижнем регистре, цифры и _")
        spec = spec if isinstance(spec, dict) else {"default": spec}
        default = spec.get("default", "")
        if isinstance(default, float) and not math.isfinite(default):
            raise StepError(f"параметр «{name}»: значение по умолчанию должно быть конечным числом")
        out[name] = {
            "label": _text(spec.get("label")) or name,
            "default": default,
        }
    return out


def check_params(params: dict, steps: list) -> None:
    """Каждый вынесенный параметр обязан быть описан — иначе ctx.params вернёт None."""
    for step in steps:
        name = step.get("param")
        if name and name not in params:
            raise StepError(f"параметр «{name}» не описан")
