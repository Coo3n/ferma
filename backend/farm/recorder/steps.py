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
    # Повтор по кругу: следующие `span` шагов — тело цикла. Сколько — `times`
    # раз или `minutes` минут (ровно одно из двух); между кругами пауза
    # pause_min…pause_max секунд; watch — сторож (ctx.on_track) на каждом круге.
    "loop": (("span",), ("times", "minutes", "pause_min", "pause_max", "watch")),
    # «С шансом»: следующие span шагов выполняются с вероятностью percent %.
    "chance": (("span", "percent"), ()),
    # «Пока не найдёшь»: крутить следующие span шагов, пока на экране не
    # появится цель (any — признаки, «любой из»), не больше tries раз.
    # on_fail — что делать, если так и не нашли: skip (идти дальше),
    # fail (остановить сценарий), ask (спросить человека).
    "until": (("span",), ("tries", "on_fail")),
    # «Если на экране»: следующие span шагов выполняются, только если цель
    # (any) видна — или, с negate, если её НЕТ. timeout — сколько секунд ждать
    # её появления. Пара «если есть» + «если нет» даёт «иначе».
    "if_seen": (("span",), ("negate", "timeout")),
    # Выйти из ближайшего повтора / «пока не найдёшь». Только внутри них.
    "break": ((), ()),
    # Закончить сценарий: result ok — как успех, fail — как ошибку с reason.
    "finish": ((), ("result", "reason")),
    # Выполнить другой сохранённый сценарий как шаг (ctx.run).
    "call": (("scenario",), ()),
    # «Если на телефоне»: следующие span шагов выполняются, только если факт
    # о телефоне верен (или, с negate, неверен). Поля — по виду check,
    # см. PHONE_CHECKS.
    "if_phone": (("span", "check"), ("negate", "package", "version", "percent", "gb",
                                     "platform")),
    # «Приложение готово»: установлено и не старее min_version; нет — поставить
    # из библиотеки APK фермы (install=False — только проверить).
    "ensure_app": (("package",), ("min_version", "install")),
}

# Блоки — шаги-рамки: тело — следующие span шагов. Вкладываются друг в друга
# не глубже BLOCK_DEPTH_MAX: «повтор → с шансом → пока не найдёшь» читается,
# четвёртый уровень — уже нет.
BLOCKS = {"loop", "chance", "until", "if_seen", "if_phone"}
LOOPS = {"loop", "until"}   # из них выходит break
FINISH_RESULTS = ("ok", "fail")
IF_SEEN_TIMEOUT_MAX = 60
BLOCK_DEPTH_MAX = 3
UNTIL_TRIES_MAX = 200
UNTIL_ON_FAIL = ("skip", "fail", "ask")

# Проверки блока «Если на телефоне» и поля, которые каждой нужны.
PHONE_CHECKS = {
    "app_installed": ("package",),
    "app_older": ("package", "version"),
    "battery_below": ("percent",),
    "offline": (),
    "space_below": ("gb",),
    "no_account": ("platform",),
}
_PHONE_FIELDS = ("package", "version", "percent", "gb", "platform")
_PHONE_WORDS = {"package": "приложение", "version": "версия", "percent": "заряд",
                "gb": "место", "platform": "аккаунт"}
VERSION_RE = re.compile(r"^\d+(\.\d+){0,4}$")

NUMERIC = {"x", "y", "x1", "y1", "x2", "y2", "duration", "seconds", "timeout",
           "span", "times", "minutes", "pause_min", "pause_max", "percent", "tries", "gb"}
BOOLEAN = {"clear", "watch", "negate", "install"}

# Потолки повтора: сутки и десять тысяч кругов — дальше это уже не сценарий,
# а забытый на ночь цикл, который держит телефон.
LOOP_TIMES_MAX = 10000
LOOP_MINUTES_MAX = 24 * 60
LOOP_PAUSE_MAX = 600

# Шаги, чьё значение можно вынести в PARAMS. Селекторы сюда не входят:
# они хранятся готовой строкой из farm/ui/selectors.py и не разбираются.
PARAMETRIZABLE = {"type", "launch_app", "open_url", "stop_app", "shell", "sleep",
                  "screenshot", "ensure_app"}


# Шаги, которым допустимы «пропустить при неудаче» и «повторить». Проверки
# экрана (expect/branch) и sleep сюда не входят: у них своя логика ожидания.
FLEXIBLE = {"click", "tap", "long_tap", "swipe", "type", "key", "launch_app",
            "open_url", "stop_app", "shell", "screenshot", "unlock", "ensure_app"}
RETRIES_MAX = 5

_LABELS = {
    "click": "Тап по элементу", "tap": "Тап", "long_tap": "Долгое нажатие",
    "swipe": "Свайп", "type": "Ввод текста", "key": "Клавиша",
    "unlock": "Разблокировать", "launch_app": "Запуск приложения",
    "stop_app": "Остановка приложения", "open_url": "Открыть ссылку",
    "shell": "Команда shell", "sleep": "Пауза", "screenshot": "Скриншот",
    "expect": "Якорь экрана", "branch": "Развилка", "loop": "Повтор",
    "chance": "С шансом", "until": "Пока не найдёшь",
    "if_seen": "Если на экране", "break": "Выйти из повтора",
    "finish": "Закончить сценарий", "call": "Сценарий",
    "if_phone": "Если на телефоне", "ensure_app": "Приложение готово",
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
    elif kind == "loop":
        tail = (f'{int(args["times"])} раз' if args.get("times")
                else f'{_minutes_text(args.get("minutes"))} мин')
    elif kind == "chance":
        tail = f'{_minutes_text(args.get("percent"))}%'
    elif kind in ("until", "if_seen"):
        m = re.search(r'="([^"]{1,40})"', ((step.get("any") or [""])[0]))
        tail = m.group(1) if m else ""
        if kind == "if_seen" and args.get("negate"):
            base = "Если нет на экране"
    elif kind == "if_phone":
        check = args.get("check")
        if check == "app_installed":
            tail = args.get("package", "")
            if args.get("negate"):
                base = "Если на телефоне нет"
        elif check == "app_older":
            tail = f'{args.get("package", "")} старее {args.get("version", "")}'
        elif check == "battery_below":
            tail = f'заряд меньше {_minutes_text(args.get("percent"))}%'
        elif check == "offline":
            tail = "нет интернета"
        elif check == "space_below":
            tail = f'свободно меньше {_minutes_text(args.get("gb"))} ГБ'
        elif check == "no_account":
            tail = f'нет аккаунта {args.get("platform", "")}'
        if args.get("negate") and check != "app_installed":
            base = "Если на телефоне НЕ"
    elif kind == "ensure_app":
        tail = args.get("package", "")
        if args.get("min_version"):
            tail += f' не ниже {args["min_version"]}'
    elif kind == "call":
        tail = args.get("scenario", "")
    elif kind == "finish":
        tail = "с ошибкой" if args.get("result") == "fail" else "успешно"
    elif kind == "click":
        m = re.search(r'(?:text|description|resourceId)\w*="([^"]{1,40})"',
                      ((step.get("selector") or {}).get("args") or ""))
        tail = m.group(1) if m else ""
    note = step.get("note")
    text = f"{base}: {tail}" if tail else base
    return f"{text} — {note}" if note else text


def _minutes_text(value) -> str:
    return f"{round(float(value or 0), 1):g}"


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
    """Признаки экрана у шага expect и цель у «пока не найдёшь» (until)."""
    if raw in (None, []):
        if kind == "expect":
            raise StepError("шагу expect нужен хотя бы один признак экрана")
        if kind == "until":
            raise StepError("«пока не найдёшь»: укажите, что искать на экране")
        if kind == "if_seen":
            raise StepError("«если на экране»: укажите, что искать")
        return None
    if kind not in ("expect", "until", "if_seen"):
        raise StepError(f"поле any допустимо только у expect, until и if_seen, не у {kind}")
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


# «Внутри» и «рядом с»: где искать цель среди одинаковых (farm/ui/scope.py).
# Строка того же вида, что селектор, но ключи — только устойчивые надписи и
# id: регулярка и номер по счёту место поиска не удержат.
SCOPE_FIELDS = {"within": "«внутри»", "near": "«рядом с»"}
SCOPE_VALUE_MAX = 200
SCOPE_KEYS_MAX = 3
_SCOPE_TEXT_KEYS = ("text", "textContains", "textStartsWith", "description",
                    "descriptionContains", "descriptionStartsWith")


def _scope(kind: str, raw, field: str) -> str | None:
    if raw in (None, ""):
        return None
    from ..ui import scope, selectors
    что = SCOPE_FIELDS[field]
    if kind != "click":
        raise StepError(f"поле {field} ({что}) допустимо только у click, не у {kind}")
    _check_kwargs(raw, что)
    sel = scope.parse_args(raw)
    if len(sel) > SCOPE_KEYS_MAX:
        raise StepError(f"{что}: не больше {SCOPE_KEYS_MAX} признаков")
    for key, value in sel.items():
        if key not in scope.ANCHOR_KEYS:
            raise StepError(f"{что}: признак «{key}» не подходит — "
                            f"допустимы {', '.join(scope.ANCHOR_KEYS)}")
        if not isinstance(value, str) or not value.strip():
            raise StepError(f"{что}: «{key}» должно быть непустой строкой")
        if len(value) > SCOPE_VALUE_MAX:
            raise StepError(f"{что}: «{key}» длиннее {SCOPE_VALUE_MAX} символов")
        if key in _SCOPE_TEXT_KEYS and selectors.is_dynamic(value):
            raise StepError(f"{что}: надпись «{value}» меняется сама (время, счётчик, "
                            f"ник) — выберите постоянную")
    return raw


def _check_scope_target(step: dict) -> None:
    """С «внутри»/«рядом с» цель ищется по дампу: ключи должны быть понятны ферме."""
    from ..ui import scope
    sel = step["selector"]
    for args in [sel["args"], *sel["fallbacks"]]:
        bad = set(scope.parse_args(args)) - scope.TARGET_KEYS
        if bad:
            raise StepError(f"признак «{sorted(bad)[0]}» нельзя сочетать с "
                            f"«внутри»/«рядом с»: {args}")


def _point_rel(raw, step: dict) -> list | None:
    """Точка шага от места поиска: у «внутри» — доли рамки контейнера (0..1),
    у «рядом с» — смещение от центра ориентира в долях экрана (-1..1).
    Без места не бывает: от чего тогда отсчитывать."""
    if raw in (None, []):
        return None
    if step["kind"] != "click":
        raise StepError(f"поле point_rel допустимо только у click, не у {step['kind']}")
    if not (step.get("within") or step.get("near")):
        raise StepError("point_rel — точка от места поиска: нужен within или near")
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise StepError("point_rel — пара чисел [x, y]")
    lo = 0 if step.get("within") else -1
    if not (lo <= x <= 1 and lo <= y <= 1):
        raise StepError("point_rel: у within доли рамки 0..1, у near смещение -1..1")
    return [round(x, 4), round(y, 4)]


# «Листать, пока не найдётся»: по выбору оператора, по умолчанию выключено.
SCROLL_DIRS = ("down", "up")
SCROLL_MAX = 10   # = farm.context.SCROLL_MAX


def _scroll(kind: str, raw) -> dict | None:
    """{dir: down|up, max: 1..10} — если цели не видно, листать и искать снова."""
    if raw in (None, {}, ""):
        return None
    if kind != "click":
        raise StepError(f"поле scroll («листать, пока не найдётся») допустимо только у click, "
                        f"не у {kind}")
    if not isinstance(raw, dict) or set(raw) != {"dir", "max"}:
        raise StepError('scroll — {"dir": "down" или "up", "max": сколько раз}')
    if raw["dir"] not in SCROLL_DIRS:
        raise StepError("scroll: направление down (вниз) или up (вверх)")
    n = raw["max"]
    плохо = f"scroll: сколько раз — целое от 1 до {SCROLL_MAX}"
    if isinstance(n, bool) or isinstance(n, float):
        raise StepError(плохо)
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise StepError(плохо)
    if str(raw["max"]).strip() != str(n) or not 1 <= n <= SCROLL_MAX:
        raise StepError(плохо)
    return {"dir": raw["dir"], "max": n}


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
    позиция карточки на холсте «Схемы», не участвует в генерации кода.
    within/near (место поиска click), optional и retries появляются, только
    когда заданы."""
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
    scoped = [f for f in SCOPE_FIELDS if raw.get(f) not in (None, "")]
    if len(scoped) > 1:
        raise StepError("у шага может быть что-то одно: «внутри» или «рядом с»")
    for field in scoped:
        step[field] = _scope(kind, raw.get(field), field)
    if scoped:
        _check_scope_target(step)
    point_rel = _point_rel(raw.get("point_rel"), step)
    if point_rel:
        step["point_rel"] = point_rel
    scroll = _scroll(kind, raw.get("scroll"))
    if scroll:
        step["scroll"] = scroll
    _check_account(kind, step["args"])
    if kind == "loop":
        _check_loop(step["args"])
    elif kind == "chance":
        _check_chance(step["args"])
    elif kind == "until":
        _check_until(step["args"])
    elif kind == "if_seen":
        _check_if_seen(step["args"])
    elif kind == "if_phone":
        _check_if_phone(step["args"])
    elif kind == "ensure_app":
        _check_ensure_app(step["args"])
    elif kind == "finish":
        _check_finish(step["args"])
    elif kind == "call":
        _check_call(step["args"])
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


def _check_loop(args: dict) -> None:
    """Повтор: целое тело, ровно одно из «раз»/«минут», разумные паузы."""
    _span(args, "повтор")
    times, minutes = args.get("times"), args.get("minutes")
    if (times is None) == (minutes is None):
        raise StepError("повтор: укажите либо сколько раз, либо сколько минут")
    if times is not None:
        if times != int(times) or not 1 <= times <= LOOP_TIMES_MAX:
            raise StepError(f"повтор: от 1 до {LOOP_TIMES_MAX} раз")
        args["times"] = int(times)
    if minutes is not None and not 0 < minutes <= LOOP_MINUTES_MAX:
        raise StepError(f"повтор: от 0 до {LOOP_MINUTES_MAX} минут")
    lo, hi = args.get("pause_min"), args.get("pause_max")
    if (lo is None) != (hi is None):
        raise StepError("повтор: пауза задаётся парой «от» и «до»")
    if lo is not None and not 0 <= lo <= hi <= LOOP_PAUSE_MAX:
        raise StepError(f"повтор: пауза от 0 до {LOOP_PAUSE_MAX} с, «от» не больше «до»")


def _span(args: dict, что: str) -> None:
    span = args["span"]
    if span != int(span) or span < 1:
        raise StepError(f"{что}: в нём должен быть хотя бы один шаг")
    args["span"] = int(span)


def _check_chance(args: dict) -> None:
    _span(args, "«с шансом»")
    if not 0 < args["percent"] <= 100:
        raise StepError("«с шансом»: от 1 до 100 %")


def _check_until(args: dict) -> None:
    _span(args, "«пока не найдёшь»")
    tries = args.get("tries", 20)
    if tries != int(tries) or not 1 <= tries <= UNTIL_TRIES_MAX:
        raise StepError(f"«пока не найдёшь»: от 1 до {UNTIL_TRIES_MAX} попыток")
    args["tries"] = int(tries)
    on_fail = args.get("on_fail") or "skip"
    if on_fail not in UNTIL_ON_FAIL:
        raise StepError("«пока не найдёшь»: если не нашли — skip, fail или ask")
    args["on_fail"] = on_fail


def _check_if_seen(args: dict) -> None:
    _span(args, "«если на экране»")
    timeout = args.get("timeout", 3)
    if not 0 <= timeout <= IF_SEEN_TIMEOUT_MAX:
        raise StepError(f"«если на экране»: ждать от 0 до {IF_SEEN_TIMEOUT_MAX} с")
    args["timeout"] = timeout
    args["negate"] = bool(args.get("negate"))


def _check_if_phone(args: dict) -> None:
    _span(args, "«если на телефоне»")
    check = args["check"]
    if check not in PHONE_CHECKS:
        raise StepError(f"«если на телефоне»: условие одно из {', '.join(PHONE_CHECKS)}")
    need = PHONE_CHECKS[check]
    for field in _PHONE_FIELDS:
        if field not in need:
            args.pop(field, None)
        elif args.get(field) in (None, ""):
            raise StepError(f"«если на телефоне»: не задано — {_PHONE_WORDS[field]}")
    from ..apklib import PACKAGE_RE
    if "package" in need and not PACKAGE_RE.match(args["package"]):
        raise StepError("«если на телефоне»: приложение — вида com.example.app")
    if "version" in need and not VERSION_RE.match(args["version"]):
        raise StepError("«если на телефоне»: версия — числа через точку, например 8.40")
    if "percent" in need:
        if not 1 <= args["percent"] <= 99:
            raise StepError("«если на телефоне»: заряд от 1 до 99 %")
        args["percent"] = int(args["percent"])
    if "gb" in need and not 0.1 <= args["gb"] <= 256:
        raise StepError("«если на телефоне»: место от 0.1 до 256 ГБ")
    if "platform" in need:
        from ..accounts import PLATFORMS
        if args["platform"] not in PLATFORMS:
            raise StepError(f"«если на телефоне»: аккаунт одной из платформ {', '.join(PLATFORMS)}")
    args["negate"] = bool(args.get("negate"))


def _check_ensure_app(args: dict) -> None:
    from ..apklib import PACKAGE_RE
    if not PACKAGE_RE.match(args["package"]):
        raise StepError("«приложение готово»: приложение — вида com.example.app")
    version = args.pop("min_version", "") or ""
    if version:
        if not VERSION_RE.match(version):
            raise StepError("«приложение готово»: версия — числа через точку, например 8.40")
        args["min_version"] = version
    args["install"] = bool(args.get("install", True))


def _check_finish(args: dict) -> None:
    result = args.get("result") or "ok"
    if result not in FINISH_RESULTS:
        raise StepError("«закончить сценарий»: ok или fail")
    args["result"] = result
    args["reason"] = _text(args.get("reason"))


def _check_call(args: dict) -> None:
    if not RUN_RE.match(args["scenario"]):
        raise StepError("сценарий: латиница в нижнем регистре, цифры и _, начиная с буквы")


def check_blocks(steps: list) -> None:
    """Тело каждого блока целиком внутри сценария и внутри своего родителя;
    вложенность не глубже BLOCK_DEPTH_MAX."""
    ends = []   # концы открытых блоков, внешний первым
    kinds = []  # их виды — break ищет среди них повтор
    for i, step in enumerate(steps):
        while ends and i > ends[-1]:
            ends.pop()
            kinds.pop()
        if step["kind"] == "break" and not LOOPS & set(kinds):
            raise StepError(f"шаг {i + 1}: «выйти из повтора» стоит вне повтора")
        if step["kind"] not in BLOCKS:
            continue
        end = i + step["args"]["span"]
        if end >= len(steps):
            raise StepError(f"шаг {i + 1}: блок захватывает шаги за концом сценария")
        if ends and end > ends[-1]:
            raise StepError(f"шаг {i + 1}: блок выходит за границу внешнего блока")
        if len(ends) >= BLOCK_DEPTH_MAX:
            raise StepError(f"шаг {i + 1}: блоки вложены глубже {BLOCK_DEPTH_MAX} уровней")
        ends.append(end)
        kinds.append(step["kind"])


check_loops = check_blocks   # прежнее имя: повторы были первыми блоками


def normalize_steps(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StepError("шаги должны быть списком")
    steps = [normalize_step(item) for item in raw]
    check_blocks(steps)
    return steps


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


def _scope_keys():
    from ..ui import scope
    return scope.ANCHOR_KEYS


def schema() -> dict:
    """Машиночитаемое описание рецепта — для внешних помощников (ИИ), которые
    собирают или правят сценарий и отправляют его в /api/recorder/validate и
    /api/recorder/save. Человеческое описание — docs/recipe-format.md."""
    return {
        "kinds": {kind: {"required": list(req), "optional": list(opt),
                         "label": _LABELS.get(kind, kind)}
                  for kind, (req, opt) in ARGS.items()},
        "blocks": sorted(BLOCKS),
        "numeric": sorted(NUMERIC),
        "boolean": sorted(BOOLEAN),
        "parametrizable": sorted(PARAMETRIZABLE),
        "flexible": sorted(FLEXIBLE),
        "account_fields": sorted(ACCOUNT_FIELDS),
        # Необязательные поля click: строка селектора контейнера/ориентира.
        "click_scope": {"within": "искать цель только внутри этого элемента",
                        "near": "среди одинаковых нажать ближайший к этому элементу",
                        "keys": list(_scope_keys()), "max_one": True,
                        "point_rel": "точка от места: у within доли рамки 0..1, "
                                     "у near смещение от центра ориентира -1..1"},
        # Необязательное поле click: листать, пока цель не найдётся.
        "click_scroll": {"dir": list(SCROLL_DIRS), "max": SCROLL_MAX,
                         "about": "не видно на экране — листать в эту сторону и искать "
                                  "снова, не больше max раз; без поля не листает"},
        "until_on_fail": list(UNTIL_ON_FAIL),
        "finish_results": list(FINISH_RESULTS),
        "phone_checks": {k: list(v) for k, v in PHONE_CHECKS.items()},
        "limits": {
            "block_depth": BLOCK_DEPTH_MAX, "until_tries": UNTIL_TRIES_MAX,
            "loop_times": LOOP_TIMES_MAX, "loop_minutes": LOOP_MINUTES_MAX,
            "loop_pause": LOOP_PAUSE_MAX, "fallbacks": MAX_FALLBACKS,
            "features": ANY_MAX, "arms": ARMS_MAX, "retries": RETRIES_MAX,
            "texts": TEXTS_MAX, "if_seen_timeout": IF_SEEN_TIMEOUT_MAX,
        },
    }
