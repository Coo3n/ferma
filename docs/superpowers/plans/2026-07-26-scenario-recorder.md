# Конструктор сценариев (Record & Play) — план реализации

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ САБ-СКИЛЛ — `superpowers:subagent-driven-development` (рекомендуется) либо `superpowers:executing-plans`. Шаги размечены чекбоксами (`- [ ]`).

**Цель:** собрать в ферме режим, где сценарий записывается кликами по живому экрану устройства, ревьюется по шагам и сохраняется готовым `scenarios/<key>.py`.

**Архитектура:** дамп UI кэшируется вперёд — читается при старте записи и заново после каждого действия, поэтому клик мгновенно улетает на устройство, а селектор берётся из кэша. Шаги живут в памяти вкладки, генерация Python и запись файла — на сервере. Селекторы не переизобретаются: используется существующий `GET /api/devices/{serial}/inspect`.

**Стек:** Python 3.9 + FastAPI + uiautomator2 на бэкенде, ванильный JS без сборки на фронте, pytest для тестов.

## Глобальные ограничения

- **Проект не под git.** `git init` не делать, коммиты не создавать. Вместо шага «Commit» каждая задача заканчивается прогоном тестов.
- **Интерпретатор — только из venv:** все команды через `.venv/bin/python -m pytest`, не через `pytest`. Запуск модулем кладёт корень репозитория в `sys.path`, иначе `import farm` в тестах падает: `tests/__init__.py` нет, и pytest добавляет в путь саму папку `tests/`.
- **Python 3.9.6.** Нельзя `match`, нельзя `X | Y` в рантайм-аннотациях без `from __future__ import annotations` (он есть во всех модулях фермы — добавлять в новые тоже).
- **`httpx` не установлен**, поэтому `fastapi.testclient.TestClient` недоступен. Тесты API вызывают функции роутера напрямую и ловят `fastapi.HTTPException`. Новых зависимостей не добавлять.
- **Язык кода и документации — русский**, как во всём проекте: докстринги, комментарии, тексты ошибок, имена тестов.
- **Комментарии объясняют «почему», не «что».** Проект держит этот стиль, см. `docs/GOTCHAS.md`.
- **Нормализованные координаты** `0..1` во всех действиях — интерфейс не знает про разрешение телефона.
- Спека: `docs/superpowers/specs/2026-07-26-scenario-recorder-design.md`.

## Карта файлов

Создаются:

| Файл | Ответственность |
|---|---|
| `farm/recorder/__init__.py` | пакет, реэкспорт |
| `farm/recorder/steps.py` | схема данных из браузера: шаги, `params`, `meta`. Нормализация и валидация. Не знает про adb, FastAPI и файлы |
| `farm/recorder/codegen.py` | `{meta, params, steps}` → текст `.py`. Чистая функция |
| `farm/recorder/save.py` | запись в `scenarios/<key>.py`, валидация ключа, защита пути |
| `farm/api/recorder.py` | `POST /api/recorder/preview`, `POST /api/recorder/save` |
| `static/js/recorder.js` | состояние `REC`, перехват действий, список шагов, ревью, сохранение |
| `static/css/recorder.css` | панель конструктора и оверлей рамок |
| `tests/test_recorder_steps.py` | валидация схемы |
| `tests/test_recorder_codegen.py` | генерация кода + интеграционный импорт |
| `tests/test_recorder_save.py` | запись файла, ключи, коллизии |
| `tests/test_recorder_api.py` | коды ответов роутеров |

Меняются:

| Файл | Что |
|---|---|
| `farm/scenarios.py` | поле `recorded` в `Scenario`, чтение атрибута `RECORDED` |
| `farm/api/scenarios.py` | `DELETE /api/scenarios/{key}` |
| `farm/api/__init__.py` | подключение роутера рекордера |
| `static/js/screen.js` | одна строка перехвата в `act()` |
| `static/js/inspector.js` | включение инспектора ставит запись на паузу |
| `static/js/scenarios.js` | значок `✒`, удаление, кнопка «Создать сценарий» |
| `static/js/app.js` | `showTab()` ставит запись на паузу при уходе с вкладки |
| `static/index.html` | разметка режима «конструктор», подключение новых файлов |
| `README.md`, `docs/GOTCHAS.md` | документация |

---

### Задача 1: Схема данных конструктора

**Файлы:**
- Создать: `farm/recorder/__init__.py`
- Создать: `farm/recorder/steps.py`
- Тест: `tests/test_recorder_steps.py`

**Интерфейсы:**
- Потребляет: ничего.
- Отдаёт: `StepError`, `PARAMETRIZABLE: set[str]`, `normalize_step(raw: dict) -> dict`, `normalize_steps(raw) -> list[dict]`, `normalize_params(raw) -> dict`, `normalize_meta(raw) -> dict`, `check_params(params: dict, steps: list[dict]) -> None`. Нормализованный шаг всегда имеет ровно ключи `kind`, `args`, `selector`, `param`, `note`.

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_recorder_steps.py`:

```python
"""Проверки схемы данных, приходящих из конструктора."""
import pytest

from farm.recorder import steps


def test_нормализация_тапа_приводит_координаты_к_float():
    result = steps.normalize_step({"kind": "tap", "args": {"x": "0.5", "y": 1}})
    assert result == {
        "kind": "tap",
        "args": {"x": 0.5, "y": 1.0},
        "selector": None,
        "param": None,
        "note": "",
    }


def test_неизвестный_kind_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "танцевать", "args": {}})


def test_нехватка_обязательного_аргумента_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "tap", "args": {"x": 0.5}})


def test_нечисловая_пауза_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "sleep", "args": {"seconds": "скоро"}})


def test_лишние_ключи_отбрасываются():
    result = steps.normalize_step({
        "kind": "key", "args": {"name": "back", "мусор": 1},
        "id": 7, "shot": "data:image/jpeg;base64,AAA", "alts": [1, 2],
    })
    assert result["args"] == {"name": "back"}
    assert set(result) == {"kind", "args", "selector", "param", "note"}


def test_шаг_click_требует_селектор_с_вызовом_click():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "click", "args": {}, "selector": None})
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click", "args": {},
            "selector": {"call": "tap", "args": "0.5, 0.5"},
        })


def test_селектор_сохраняет_вызов_и_аргументы():
    result = steps.normalize_step({
        "kind": "click", "args": {},
        "selector": {"call": "click", "args": 'resourceId="a:id/b"',
                     "matches": 1, "fragile": False},
    })
    assert result["selector"] == {"call": "click", "args": 'resourceId="a:id/b"'}


def test_параметр_разрешён_только_для_шагов_со_значением():
    ok = steps.normalize_step({"kind": "type", "args": {"value": "x"}, "param": "login"})
    assert ok["param"] == "login"
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "key", "args": {"name": "back"}, "param": "login"})


def test_кривое_имя_параметра_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "type", "args": {"value": "x"}, "param": "Логин"})


def test_метка_обрезается_и_теряет_переводы_строк():
    result = steps.normalize_step({
        "kind": "key", "args": {"name": "back"}, "note": "  Кнопка\nназад  ",
    })
    assert result["note"] == "Кнопка назад"


def test_нормализация_meta_требует_название():
    with pytest.raises(steps.StepError):
        steps.normalize_meta({"name": "   "})
    assert steps.normalize_meta({"name": " Логин "}) == {
        "name": "Логин", "description": "", "watch_popups": True,
    }


def test_нормализация_params_проверяет_имена():
    with pytest.raises(steps.StepError):
        steps.normalize_params({"Логин": {"label": "Логин", "default": "x"}})
    assert steps.normalize_params({"login": {"default": "x"}}) == {
        "login": {"label": "login", "default": "x"},
    }


def test_шаг_ссылается_на_необъявленный_параметр():
    items = [steps.normalize_step({"kind": "type", "args": {"value": "x"}, "param": "login"})]
    with pytest.raises(steps.StepError):
        steps.check_params({}, items)
    steps.check_params({"login": {"label": "Логин", "default": "x"}}, items)
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_steps.py -q`
Ожидание: `ModuleNotFoundError: No module named 'farm.recorder'`.

- [ ] **Шаг 3: Написать реализацию**

Создать `farm/recorder/__init__.py`:

```python
"""Конструктор сценариев: схема шагов, генерация кода, запись файла."""
from . import codegen, save, steps

__all__ = ["codegen", "save", "steps"]
```

На этом шаге `codegen` и `save` ещё не существуют — импорт временно оставить только на `steps`:

```python
"""Конструктор сценариев: схема шагов, генерация кода, запись файла."""
from . import steps

__all__ = ["steps"]
```

Создать `farm/recorder/steps.py`:

```python
"""Схема данных, приходящих из конструктора в браузере.

Модуль намеренно не знает ни про adb, ни про FastAPI, ни про файловую систему:
на входе словари из JSON, на выходе они же, но проверенные. Это условие
тестируемости — то же, что у farm/ui/tree.py (см. docs/GOTCHAS.md).
"""
from __future__ import annotations

import re

PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

# kind -> (обязательные аргументы, необязательные)
ARGS = {
    "click": ((), ()),
    "tap": (("x", "y"), ()),
    "long_tap": (("x", "y"), ("duration",)),
    "swipe": (("x1", "y1", "x2", "y2"), ("duration",)),
    "type": (("value",), ("clear",)),
    "key": (("name",), ()),
    "unlock": ((), ()),
    "launch_app": (("package",), ()),
    "open_url": (("url",), ()),
    "stop_app": (("package",), ()),
    "sleep": (("seconds",), ()),
    "screenshot": ((), ("name",)),
}

NUMERIC = {"x", "y", "x1", "y1", "x2", "y2", "duration", "seconds"}
BOOLEAN = {"clear"}

# Шаги, чьё значение можно вынести в PARAMS. Селекторы сюда не входят:
# они хранятся готовой строкой из farm/ui/selectors.py и не разбираются.
PARAMETRIZABLE = {"type", "launch_app", "open_url", "stop_app", "sleep", "screenshot"}


class StepError(ValueError):
    """Данные конструктора не проходят проверку — запрос отвергается с 400."""


def _text(value) -> str:
    """Однострочная строка: переводы строк ломают и комментарий, и метку."""
    return " ".join(str(value or "").split())


def _selector(kind: str, raw) -> dict | None:
    if kind != "click":
        return None
    if not isinstance(raw, dict):
        raise StepError("шаг click без селектора")
    call, args = raw.get("call"), raw.get("args")
    if call != "click" or not isinstance(args, str) or not args.strip():
        raise StepError("селектор шага click должен быть вызовом click с аргументами")
    return {"call": "click", "args": args}


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
            except (TypeError, ValueError):
                raise StepError(f"аргумент «{name}» шага {kind} должен быть числом")
        elif name in BOOLEAN:
            value = bool(value)
        else:
            value = str(value)
        out[name] = value
    return out


def normalize_step(raw) -> dict:
    """Проверенный шаг ровно с ключами kind, args, selector, param, note."""
    if not isinstance(raw, dict):
        raise StepError("шаг должен быть объектом")
    kind = raw.get("kind")
    if kind not in ARGS:
        raise StepError(f"неизвестный шаг: {kind!r}")
    return {
        "kind": kind,
        "args": _args(kind, raw.get("args")),
        "selector": _selector(kind, raw.get("selector")),
        "param": _param(kind, raw.get("param")),
        "note": _text(raw.get("note")),
    }


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
        out[name] = {
            "label": _text(spec.get("label")) or name,
            "default": spec.get("default", ""),
        }
    return out


def check_params(params: dict, steps: list) -> None:
    """Каждый вынесенный параметр обязан быть описан — иначе ctx.params вернёт None."""
    for step in steps:
        name = step.get("param")
        if name and name not in params:
            raise StepError(f"параметр «{name}» не описан")
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_steps.py -q`
Ожидание: `13 passed`.

---

### Задача 2: Генерация исходника сценария

**Файлы:**
- Создать: `farm/recorder/codegen.py`
- Изменить: `farm/recorder/__init__.py`
- Тест: `tests/test_recorder_codegen.py`

**Интерфейсы:**
- Потребляет: `steps.normalize_step`, `steps.PARAMETRIZABLE` из задачи 1.
- Отдаёт: `literal(value: str) -> str`, `render(meta: dict, params: dict, steps: list, today: datetime.date | None = None) -> str`. `render` возвращает текст файла с завершающим `\n`.

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_recorder_codegen.py`:

```python
"""Генерация исходника сценария из записанных шагов."""
from datetime import date

from farm.recorder import codegen, steps

DAY = date(2026, 7, 26)
META = {"name": "Тест", "description": "", "watch_popups": False}


def build(*raw):
    return [steps.normalize_step(item) for item in raw]


def body(text):
    """Строки тела run(ctx) без отступа — то, ради чего пишется тест."""
    lines = text.splitlines()
    start = lines.index("def run(ctx):") + 1
    return [line[4:] for line in lines[start:] if line.strip()]


def test_каждый_шаг_даёт_ожидаемую_строку():
    result = codegen.render(META, {}, build(
        {"kind": "click", "args": {},
         "selector": {"call": "click", "args": 'resourceId="a:id/b"'}},
        {"kind": "tap", "args": {"x": 0.5, "y": 0.25}},
        {"kind": "long_tap", "args": {"x": 0.5, "y": 0.25, "duration": 1.0}},
        {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.75, "x2": 0.5, "y2": 0.3}},
        {"kind": "type", "args": {"value": "привет"}},
        {"kind": "type", "args": {"value": "привет", "clear": True}},
        {"kind": "key", "args": {"name": "back"}},
        {"kind": "unlock", "args": {}},
        {"kind": "launch_app", "args": {"package": "com.a"}},
        {"kind": "stop_app", "args": {"package": "com.a"}},
        {"kind": "open_url", "args": {"url": "https://a.b"}},
        {"kind": "sleep", "args": {"seconds": 1.5}},
        {"kind": "screenshot", "args": {"name": "итог"}},
        {"kind": "screenshot", "args": {}},
    ), today=DAY)

    assert body(result) == [
        'ctx.click(resourceId="a:id/b")',
        "ctx.tap(0.5, 0.25)",
        "ctx.long_tap(0.5, 0.25, 1)",
        "ctx.swipe(0.5, 0.75, 0.5, 0.3, 0.25)",
        'ctx.type("привет")',
        'ctx.type("привет", clear=True)',
        'ctx.key("back")',
        "ctx.unlock()",
        'ctx.launch_app("com.a")',
        'ctx.stop_app("com.a")',
        'ctx.open_url("https://a.b")',
        "ctx.sleep(1.5)",
        'ctx.screenshot("итог")',
        "ctx.screenshot()",
    ]


def test_метка_становится_комментарием():
    result = codegen.render(META, {}, build(
        {"kind": "key", "args": {"name": "back"}, "note": "Кнопка назад"},
    ), today=DAY)
    assert 'ctx.key("back")  # Кнопка назад' in result


def test_экранирование_кавычек_и_бэкслешей():
    assert codegen.literal('он сказал "да"') == '"он сказал \\"да\\""'
    assert codegen.literal("путь\\к") == '"путь\\\\к"'
    assert codegen.literal("две\nстроки") == '"две\\nстроки"'


def test_экранирование_в_названии_и_описании():
    result = codegen.render(
        {"name": 'Тест "боевой"', "description": "путь\\сюда", "watch_popups": False},
        {}, build({"kind": "unlock", "args": {}}), today=DAY)
    assert 'NAME = "Тест \\"боевой\\""' in result
    assert 'DESCRIPTION = "путь\\\\сюда"' in result


def test_параметр_заменяет_литерал_и_попадает_в_PARAMS():
    result = codegen.render(META, {"login": {"label": "Логин", "default": "user@a.b"}}, build(
        {"kind": "type", "args": {"value": "user@a.b"}, "param": "login"},
    ), today=DAY)
    assert 'ctx.type(ctx.params["login"])' in result
    assert '"login": {"label": "Логин", "default": "user@a.b"},' in result
    assert '"user@a.b")' not in result


def test_числовой_default_остаётся_числом():
    result = codegen.render(META, {"wait": {"label": "Пауза", "default": 2.5}}, build(
        {"kind": "sleep", "args": {"seconds": 2.5}, "param": "wait"},
    ), today=DAY)
    assert '"wait": {"label": "Пауза", "default": 2.5},' in result
    assert "ctx.sleep(ctx.params[\"wait\"])" in result


def test_без_параметров_блок_PARAMS_не_печатается():
    result = codegen.render(META, {}, build({"kind": "unlock", "args": {}}), today=DAY)
    assert "PARAMS" not in result


def test_watch_popups_управляется_галкой():
    on = codegen.render({"name": "Т", "description": "", "watch_popups": True}, {},
                        build({"kind": "unlock", "args": {}}), today=DAY)
    assert "ctx.watch_popups()" in on
    assert "ctx.watch_popups()" not in codegen.render(META, {},
                                                      build({"kind": "unlock", "args": {}}),
                                                      today=DAY)


def test_пустое_тело_получает_pass():
    result = codegen.render(META, {}, [], today=DAY)
    assert body(result) == ["pass"]


def test_шапка_файла():
    result = codegen.render(META, {}, build({"kind": "unlock", "args": {}}), today=DAY)
    assert result.startswith('"""Записано конструктором фермы 26.07.2026."""\n')
    assert "RECORDED = True" in result
    assert result.endswith("\n")
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_codegen.py -q`
Ожидание: `ImportError: cannot import name 'codegen'`.

- [ ] **Шаг 3: Написать реализацию**

Создать `farm/recorder/codegen.py`:

```python
"""Сборка исходника сценария из проверенных шагов.

На входе словари, на выходе строка: ни adb, ни FastAPI, ни файловой системы.
Благодаря этому весь генератор покрывается тестами без телефона.
"""
from __future__ import annotations

from datetime import date

INDENT = "    "


def literal(value) -> str:
    """Строковый литерал Python.

    Дублирует farm/ui/selectors._literal сознательно. Там литерал строится для
    показа в интерфейсе, здесь отвечает за то, что весь файл вообще
    импортируется, — поэтому дополнительно гасит переводы строк. Связывать два
    модуля ради четырёх замен дороже, чем повторить их.
    """
    return '"' + (str(value)
                  .replace("\\", "\\\\")
                  .replace('"', '\\"')
                  .replace("\r", "\\r")
                  .replace("\n", "\\n")) + '"'


def _num(value) -> str:
    """Число без хвостовых нулей: 1.0 → 1, 0.4200 → 0.42."""
    return f"{round(float(value), 3):g}"


def _default(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return _num(value)
    return literal(value)


def _value(step: dict, fallback: str) -> str:
    """Вынесенный параметр вместо литерала, если он задан."""
    name = step.get("param")
    return f"ctx.params[{literal(name)}]" if name else fallback


def _call(step: dict) -> str:
    kind, args = step["kind"], step["args"]

    if kind == "click":
        return f'ctx.click({step["selector"]["args"]})'
    if kind == "tap":
        return f'ctx.tap({_num(args["x"])}, {_num(args["y"])})'
    if kind == "long_tap":
        return (f'ctx.long_tap({_num(args["x"])}, {_num(args["y"])}, '
                f'{_num(args.get("duration", 0.8))})')
    if kind == "swipe":
        return (f'ctx.swipe({_num(args["x1"])}, {_num(args["y1"])}, '
                f'{_num(args["x2"])}, {_num(args["y2"])}, '
                f'{_num(args.get("duration", 0.25))})')
    if kind == "type":
        tail = ", clear=True" if args.get("clear") else ""
        return f'ctx.type({_value(step, literal(args["value"]))}{tail})'
    if kind == "key":
        return f'ctx.key({literal(args["name"])})'
    if kind == "unlock":
        return "ctx.unlock()"
    if kind == "launch_app":
        return f'ctx.launch_app({_value(step, literal(args["package"]))})'
    if kind == "stop_app":
        return f'ctx.stop_app({_value(step, literal(args["package"]))})'
    if kind == "open_url":
        return f'ctx.open_url({_value(step, literal(args["url"]))})'
    if kind == "sleep":
        return f'ctx.sleep({_value(step, _num(args["seconds"]))})'
    if kind == "screenshot":
        name = args.get("name", "")
        inner = _value(step, literal(name)) if (name or step.get("param")) else ""
        return f"ctx.screenshot({inner})"
    raise ValueError(f"неизвестный шаг: {kind}")  # недостижимо после normalize_step


def _header(meta: dict, params: dict, today: date) -> list:
    out = [f'"""Записано конструктором фермы {today.strftime("%d.%m.%Y")}."""',
           "RECORDED = True",
           f'NAME = {literal(meta["name"])}']
    if meta.get("description"):
        out.append(f'DESCRIPTION = {literal(meta["description"])}')
    if params:
        out.append("PARAMS = {")
        for name, spec in params.items():
            out.append(f'{INDENT}{literal(name)}: '
                       f'{{"label": {literal(spec["label"])}, '
                       f'"default": {_default(spec["default"])}}},')
        out.append("}")
    return out


def render(meta: dict, params: dict, steps: list, today: date = None) -> str:
    """Готовый текст файла сценария."""
    out = _header(meta, params, today or date.today())
    out += ["", "", "def run(ctx):"]

    body = []
    if meta.get("watch_popups", True):
        body.append("ctx.watch_popups()")
    for step in steps:
        note = step.get("note")
        body.append(_call(step) + (f"  # {note}" if note else ""))
    if not body:
        body.append("pass")  # пустой def run(ctx) — синтаксическая ошибка

    out += [INDENT + line for line in body]
    return "\n".join(out) + "\n"
```

Изменить `farm/recorder/__init__.py`:

```python
"""Конструктор сценариев: схема шагов, генерация кода, запись файла."""
from . import codegen, steps

__all__ = ["codegen", "steps"]
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_codegen.py -q`
Ожидание: `10 passed`.

- [ ] **Шаг 5: Прогнать всё**

Запустить: `.venv/bin/python -m pytest -q`
Ожидание: `23 passed`.

---

### Задача 3: Флаг «записано конструктором» и интеграционный импорт

**Файлы:**
- Изменить: `farm/scenarios.py:22-41` (dataclass `Scenario` и `to_dict`), `farm/scenarios.py:47-72` (`_load_file`)
- Тест: `tests/test_recorder_codegen.py` (дописать)

**Интерфейсы:**
- Потребляет: `codegen.render` из задачи 2.
- Отдаёт: `Scenario.recorded: bool`, ключ `recorded` в `Scenario.to_dict()`. Задача 5 опирается на него в `DELETE /api/scenarios/{key}`, фронт — в значке `✒`.

Это главный тест плана: он ловит синтаксис, отступы и экранирование разом — сгенерированный файл должен реально импортироваться фермой.

- [ ] **Шаг 1: Написать падающий тест**

Дописать в конец `tests/test_recorder_codegen.py`:

```python
def test_сгенерированный_файл_импортируется_фермой(tmp_path, monkeypatch):
    """Главная проверка: ферма обязана принять то, что сгенерировал конструктор."""
    from farm import config, scenarios

    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()

    source = codegen.render(
        {"name": 'Логин "боевой"', "description": "путь\\сюда",
         "watch_popups": True},
        {"login": {"label": "Логин", "default": "user@a.b"},
         "wait": {"label": "Пауза", "default": 2.5}},
        build(
            {"kind": "launch_app", "args": {"package": "com.a"}},
            {"kind": "click", "args": {},
             "selector": {"call": "click", "args": 'resourceId="com.a:id/email"'},
             "note": "Поле «Почта»"},
            {"kind": "type", "args": {"value": "user@a.b"}, "param": "login"},
            {"kind": "sleep", "args": {"seconds": 2.5}, "param": "wait"},
            {"kind": "screenshot", "args": {"name": "итог"}},
        ),
        today=DAY,
    )
    (tmp_path / "logins.py").write_text(source, "utf-8")

    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["logins"].error == ""
    assert found["logins"].recorded is True
    assert found["logins"].name == 'Логин "боевой"'
    assert found["logins"].params["login"]["default"] == "user@a.b"
    assert found["logins"].to_dict()["recorded"] is True


def test_обычный_сценарий_не_помечен_записанным(tmp_path, monkeypatch):
    from farm import config, scenarios

    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    (tmp_path / "ручной.py").write_text("def run(ctx):\n    pass\n", "utf-8")

    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["ручной"].recorded is False


def test_сломанный_записанный_файл_остаётся_помеченным(tmp_path, monkeypatch):
    """Иначе битый файл нельзя было бы удалить из интерфейса."""
    from farm import config, scenarios

    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    (tmp_path / "битый.py").write_text(
        'RECORDED = True\nNAME = "Битый"\nдef run(ctx):\n', "utf-8")

    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["битый"].error != ""
    assert found["битый"].recorded is True
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_codegen.py -q -k импорт`
Ожидание: `AttributeError: 'Scenario' object has no attribute 'recorded'`.

- [ ] **Шаг 3: Написать реализацию**

В `farm/scenarios.py` заменить блок dataclass и `to_dict` (строки 22–41) на:

```python
@dataclass
class Scenario:
    key: str
    name: str
    description: str
    params: dict
    path: str
    mtime: float
    error: str = ""
    recorded: bool = False
    module: object | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "params": self.params,
            "path": self.path,
            "error": self.error,
            "recorded": self.recorded,
        }
```

Там же добавить константу под `log` (после строки 19):

```python
# Маркер файлов, собранных конструктором. Ищется и в тексте: у сломанного файла
# модуль не импортируется, а удалять его из интерфейса всё равно нужно.
RECORDED_MARK = "RECORDED = True"
MARK_SCAN_CHARS = 400
```

И заменить `_load_file` (строки 47–72) на:

```python
def _marked(path: Path) -> bool:
    try:
        return RECORDED_MARK in path.read_text("utf-8")[:MARK_SCAN_CHARS]
    except OSError:
        return False


def _load_file(path: Path) -> Scenario:
    key = path.stem
    mtime = path.stat().st_mtime
    mod_name = f"farm_scenario_{key}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return Scenario(key, key, "", {}, str(path), mtime,
                        error="не удалось прочитать файл", recorded=_marked(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001
        return Scenario(key, key, "", {}, str(path), mtime,
                        error=traceback.format_exc(limit=3), recorded=_marked(path))

    if not callable(getattr(module, "run", None)):
        return Scenario(key, key, "", {}, str(path), mtime,
                        error="нет функции run(ctx)",
                        recorded=bool(getattr(module, "RECORDED", False)))

    return Scenario(
        key=key,
        name=getattr(module, "NAME", key),
        description=getattr(module, "DESCRIPTION", (module.__doc__ or "").strip()),
        params=getattr(module, "PARAMS", {}) or {},
        path=str(path),
        mtime=mtime,
        recorded=bool(getattr(module, "RECORDED", False)),
        module=module,
    )
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Запустить: `.venv/bin/python -m pytest -q`
Ожидание: `26 passed`.

- [ ] **Шаг 5: Проверить, что живые сценарии не сломались**

Запустить: `.venv/bin/python -c "from farm import scenarios; print([(s.key, s.recorded, s.error[:40]) for s in scenarios.discover(force=True)])"`
Ожидание: три сценария (`open_app`, `prepare_device`, `tap_by_text`), у всех `False` и пустая ошибка.

---

### Задача 4: Запись файла сценария

**Файлы:**
- Создать: `farm/recorder/save.py`
- Изменить: `farm/recorder/__init__.py`
- Тест: `tests/test_recorder_save.py`

**Интерфейсы:**
- Потребляет: `codegen.render` из задачи 2, `config.SCENARIOS_DIR`.
- Отдаёт: `SaveError`, `Conflict`, `target_path(key: str) -> Path`, `save(key, meta, params, steps, overwrite=False) -> Path`. Задача 5 маппит `Conflict` в 409, `SaveError` в 400.

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_recorder_save.py`:

```python
"""Запись сгенерированного сценария в папку scenarios/."""
import pytest

from farm import config
from farm.recorder import save, steps

META = {"name": "Тест", "description": "", "watch_popups": False}
STEPS = [steps.normalize_step({"kind": "unlock", "args": {}})]


@pytest.fixture
def scen_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("key", [
    "../../беда", "_скрытый", "Верхний", "с пробелом", "", None, "x" * 49, "9начало",
])
def test_плохой_ключ_отвергается(scen_dir, key):
    with pytest.raises(save.SaveError):
        save.target_path(key)


def test_хороший_ключ_даёт_путь_внутри_папки(scen_dir):
    assert save.target_path("login_flow") == scen_dir / "login_flow.py"


def test_сохранение_создаёт_файл(scen_dir):
    path = save.save("login_flow", META, {}, STEPS)
    assert path.exists()
    assert "ctx.unlock()" in path.read_text("utf-8")


def test_пустой_список_шагов_отвергается(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("login_flow", META, {}, [])


def test_коллизия_без_перезаписи_даёт_Conflict(scen_dir):
    save.save("login_flow", META, {}, STEPS)
    with pytest.raises(save.Conflict):
        save.save("login_flow", META, {}, STEPS)


def test_перезапись_разрешена_явным_флагом(scen_dir):
    save.save("login_flow", META, {}, STEPS)
    other = [steps.normalize_step({"kind": "key", "args": {"name": "back"}})]
    path = save.save("login_flow", META, {}, other, overwrite=True)
    text = path.read_text("utf-8")
    assert 'ctx.key("back")' in text
    assert "ctx.unlock()" not in text
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_save.py -q`
Ожидание: `ImportError: cannot import name 'save'`.

- [ ] **Шаг 3: Написать реализацию**

Создать `farm/recorder/save.py`:

```python
"""Запись сгенерированного сценария в папку scenarios/."""
from __future__ import annotations

import re
from pathlib import Path

from .. import config
from . import codegen

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class SaveError(ValueError):
    """Некорректный ключ, путь вне папки или пустая запись — 400."""


class Conflict(ValueError):
    """Файл уже существует, перезапись не разрешена — 409."""


def target_path(key) -> Path:
    """Путь файла сценария. Ключ проверяется дважды намеренно.

    Регулярка уже запрещает точки и слеши, но проверка `is_relative_to`
    остаётся: она не даст выйти за папку, даже если правило когда-нибудь
    ослабят. Нижний регистр и запрет ведущего `_` не косметика — `discover()`
    пропускает файлы, начинающиеся с подчёркивания.
    """
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise SaveError(
            "имя файла: латиница в нижнем регистре, цифры и _, начиная с буквы")
    root = Path(config.SCENARIOS_DIR).resolve()
    path = (root / f"{key}.py").resolve()
    if not path.is_relative_to(root):
        raise SaveError("путь вне папки сценариев")
    return path


def save(key, meta: dict, params: dict, steps: list, overwrite: bool = False) -> Path:
    if not steps:
        raise SaveError("нет ни одного шага")
    path = target_path(key)
    if path.exists() and not overwrite:
        raise Conflict(f"сценарий «{key}» уже существует")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(codegen.render(meta, params, steps), "utf-8")
    return path
```

Изменить `farm/recorder/__init__.py`:

```python
"""Конструктор сценариев: схема шагов, генерация кода, запись файла."""
from . import codegen, save, steps

__all__ = ["codegen", "save", "steps"]
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_save.py -q`
Ожидание: `13 passed`.

---

### Задача 5: HTTP-слой конструктора

**Файлы:**
- Создать: `farm/api/recorder.py`
- Изменить: `farm/api/__init__.py`, `farm/api/scenarios.py`
- Тест: `tests/test_recorder_api.py`

**Интерфейсы:**
- Потребляет: `steps.normalize_*`, `steps.check_params`, `codegen.render`, `save.save`, `save.Conflict`, `save.SaveError`, `Scenario.recorded`.
- Отдаёт: `POST /api/recorder/preview` → `text/plain`; `POST /api/recorder/save` → `{key, path}`; `DELETE /api/scenarios/{key}` → `{ok: true}`. Фронт задач 6–9 обращается только к ним.

`httpx` в окружении нет, поэтому `TestClient` не используется: тесты вызывают функции роутера напрямую.

- [ ] **Шаг 1: Написать падающий тест**

Создать `tests/test_recorder_api.py`:

```python
"""Коды ответов конструктора. TestClient недоступен — зовём функции роутера."""
import pytest
from fastapi import HTTPException

from farm import config, scenarios
from farm.api import recorder as api_recorder
from farm.api import scenarios as api_scenarios

META = {"name": "Тест", "watch_popups": False}
STEPS = [{"kind": "unlock", "args": {}}]


@pytest.fixture
def scen_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    return tmp_path


def test_предпросмотр_возвращает_исходник():
    text = api_recorder.preview({"meta": META, "params": {}, "steps": STEPS})
    assert "def run(ctx):" in text
    assert "ctx.unlock()" in text


def test_кривой_шаг_даёт_400():
    with pytest.raises(HTTPException) as e:
        api_recorder.preview({"meta": META, "steps": [{"kind": "танцевать"}]})
    assert e.value.status_code == 400


def test_необъявленный_параметр_даёт_400():
    with pytest.raises(HTTPException) as e:
        api_recorder.preview({
            "meta": META, "params": {},
            "steps": [{"kind": "type", "args": {"value": "x"}, "param": "login"}],
        })
    assert e.value.status_code == 400


def test_сохранение_создаёт_файл_и_он_виден_в_списке(scen_dir):
    result = api_recorder.save_scenario(
        {"key": "flow_ok", "meta": META, "steps": STEPS})
    assert result["key"] == "flow_ok"
    assert (scen_dir / "flow_ok.py").exists()
    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["flow_ok"].recorded is True


def test_кириллический_ключ_даёт_400(scen_dir):
    with pytest.raises(HTTPException) as e:
        api_recorder.save_scenario({"key": "поток", "meta": META, "steps": STEPS})
    assert e.value.status_code == 400


def test_коллизия_даёт_409(scen_dir):
    api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    with pytest.raises(HTTPException) as e:
        api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    assert e.value.status_code == 409


def test_перезапись_проходит(scen_dir):
    api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    result = api_recorder.save_scenario(
        {"key": "flow", "meta": META, "steps": STEPS, "overwrite": True})
    assert result["key"] == "flow"


def test_записанный_сценарий_удаляется(scen_dir):
    api_recorder.save_scenario({"key": "flow", "meta": META, "steps": STEPS})
    assert api_scenarios.delete_scenario("flow") == {"ok": True}
    assert not (scen_dir / "flow.py").exists()


def test_ручной_сценарий_удалить_нельзя(scen_dir):
    (scen_dir / "ручной.py").write_text("def run(ctx):\n    pass\n", "utf-8")
    with pytest.raises(HTTPException) as e:
        api_scenarios.delete_scenario("ручной")
    assert e.value.status_code == 403


def test_удаление_отсутствующего_даёт_404(scen_dir):
    with pytest.raises(HTTPException) as e:
        api_scenarios.delete_scenario("нету")
    assert e.value.status_code == 404
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Запустить: `.venv/bin/python -m pytest tests/test_recorder_api.py -q`
Ожидание: `ImportError: cannot import name 'recorder' from 'farm.api'`.

- [ ] **Шаг 3: Написать реализацию**

Создать `farm/api/recorder.py`:

```python
"""Конструктор сценариев: предпросмотр кода и сохранение файла."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import PlainTextResponse

from ..recorder import codegen, save as saver, steps as schema

router = APIRouter(prefix="/api/recorder")


def _parse(payload: dict):
    """Разбор общего тела обоих запросов: meta, params и шаги."""
    try:
        meta = schema.normalize_meta(payload.get("meta"))
        params = schema.normalize_params(payload.get("params"))
        items = schema.normalize_steps(payload.get("steps"))
        schema.check_params(params, items)
    except schema.StepError as e:
        raise HTTPException(400, str(e))
    return meta, params, items


@router.post("/preview", response_class=PlainTextResponse)
def preview(payload: dict = Body(...)):
    meta, params, items = _parse(payload)
    return codegen.render(meta, params, items)


@router.post("/save")
def save_scenario(payload: dict = Body(...)):
    meta, params, items = _parse(payload)
    try:
        path = saver.save(payload.get("key"), meta, params, items,
                          bool(payload.get("overwrite")))
    except saver.Conflict as e:
        raise HTTPException(409, str(e))
    except saver.SaveError as e:
        raise HTTPException(400, str(e))
    return {"key": payload.get("key"), "path": str(path)}
```

В `farm/api/scenarios.py` дописать в конец файла (`Path` там уже импортирован, строка 4):

```python
@router.delete("/api/scenarios/{key}")
def delete_scenario(key: str):
    """Удалять можно только записанное конструктором — чужой код не трогаем."""
    scenario = scenarios.get(key)
    if scenario is None:
        raise HTTPException(404, "сценарий не найден")
    if not scenario.recorded:
        raise HTTPException(403, "удалять можно только сценарии из конструктора")
    Path(scenario.path).unlink(missing_ok=True)
    scenarios.discover(force=True)
    return {"ok": True}
```

В `farm/api/__init__.py` заменить содержимое на:

```python
"""REST-слой фермы, собранный из роутеров по зонам ответственности."""
from fastapi import APIRouter

from . import devices, jobs, recorder, scenarios, screen, system

router = APIRouter()
router.include_router(system.router)
router.include_router(devices.router)
router.include_router(screen.router)
router.include_router(scenarios.router)
router.include_router(jobs.router)
router.include_router(recorder.router)

__all__ = ["router"]
```

- [ ] **Шаг 4: Убедиться, что тесты проходят**

Запустить: `.venv/bin/python -m pytest -q`
Ожидание: `49 passed`.

- [ ] **Шаг 5: Проверить, что сервер поднимается и маршруты на месте**

Запустить: `.venv/bin/python -c "from farm.server import app; print([r.path for r in app.routes if 'recorder' in r.path or r.path.startswith('/api/scenarios')])"`
Ожидание: список содержит `/api/recorder/preview`, `/api/recorder/save`, `/api/scenarios/{key}`.

---

### Задача 6: Ядро записи на фронте

**Файлы:**
- Создать: `static/js/recorder.js`
- Изменить: `static/js/screen.js:64-75` (`act`), `static/js/inspector.js:37-38` (`inspectorLoad`), `static/js/app.js:12-18` (`showTab`), `static/index.html:97-109` (`#pane-scen`), `static/index.html:199-207` (подключение скриптов)

**Интерфейсы:**
- Потребляет: `S`, `$`, `esc`, `toast`, `api`, `post` из `core.js`; `GET /api/devices/{serial}/inspect`; `inspectorOff()` из `inspector.js`.
- Отдаёт: глобальные `window.REC`, `recNote(payload)`, `recOpen()`, `recClose()`, `recStart()`, `recPause()`, `recStop()`, `recRender()`, `recAddSleep()`, `recAddShot()`. Задачи 7–9 дополняют этот же файл.

- [ ] **Шаг 1: Разметка режимов во вкладке «Сценарии»**

В `static/index.html` заменить блок `<div class="pane on" id="pane-scen">…</div>` (строки 97–109) на:

```html
        <div class="pane on" id="pane-scen">
            <div id="scenList" class="mode">
                <div class="box" style="flex:0 0 auto">
                    <button class="sm" style="width:100%" onclick="recOpen()">
                        ✎ Создать сценарий записью
                    </button>
                </div>
                <div class="scroll" id="scList" style="flex:0 0 auto;max-height:42%"></div>
                <div class="box" id="scParams" style="flex:0 0 auto"></div>
                <div class="box" style="flex:0 0 auto">
                    <div class="row">
                        <label>Повторов</label>
                        <input type="number" id="repeat" value="1" min="1" max="200" style="width:70px">
                        <span class="sp" style="flex:1"></span>
                        <span class="stat" id="runTarget">устройств: 0</span>
                    </div>
                    <button class="primary" style="width:100%" onclick="runScenario()">▶ Запустить на выбранных</button>
                </div>
            </div>

            <div id="scenBuild" class="mode" style="display:none">
                <div class="colhead" style="border-top:none">
                    <button class="sm" onclick="recClose()">← назад</button>
                    <span class="sp" style="flex:1"></span>
                    <span class="stat" id="recState">не записывается</span>
                </div>
                <div class="box" style="flex:0 0 auto">
                    <div class="row">
                        <button class="sm" id="btnRecStart" onclick="recStart()">● Запись</button>
                        <button class="sm" id="btnRecPause" onclick="recPause()" disabled>⏸ пауза</button>
                        <button class="sm" id="btnRecStop" onclick="recStop()" disabled>■ стоп</button>
                        <span class="sp" style="flex:1"></span>
                        <label class="kb">
                            <input type="checkbox" id="recPauses" style="accent-color:var(--accent)"
                                   onchange="REC.pauses=this.checked"> писать паузы
                        </label>
                    </div>
                    <div class="row">
                        <button class="sm" onclick="recAddSleep()">+ пауза</button>
                        <button class="sm" onclick="recAddShot()">+ скриншот</button>
                        <span class="sp" style="flex:1"></span>
                        <button class="sm" onclick="recPreview()">⟨⟩ код</button>
                        <button class="primary" onclick="recSaveForm()">💾 Сохранить</button>
                    </div>
                    <div class="warn" id="recBanner" style="display:none;margin-top:8px"></div>
                </div>
                <div class="scroll" id="recSteps"></div>
            </div>
        </div>
```

Там же, в блоке скриптов (строки 199–207), добавить `recorder.js` перед `app.js`:

```html
<script src="/static/js/inspector.js"></script>
<script src="/static/js/recorder.js"></script>
<script src="/static/js/app.js"></script>
```

И в `<head>` после `inspector.css`:

```html
    <link rel="stylesheet" href="/static/css/recorder.css">
```

Создать пустой `static/css/recorder.css` с одной строкой — наполнение в задаче 8:

```css
/* Конструктор сценариев: панель шагов и оверлей рамок. */
.mode { display: flex; flex-direction: column; flex: 1; min-height: 0; }
```

- [ ] **Шаг 2: Перехват действий**

В `static/js/screen.js` заменить функцию `act` (строки 64–75) на:

```javascript
async function act(payload) {
    if (!S.active) {
        toast('устройство не выбрано', 'bad');
        return;
    }
    try {
        const result = await post(`/api/devices/${S.active}/action`, payload);
        /* Единственная точка перехвата: через act() идут не только жесты,
           но и launch/stop/url со вкладки «Устройство». */
        if (window.REC && REC.on) recNote(payload);
        return result;
    } catch (e) {
        toast(e.message, 'bad');
        throw e;
    }
}
```

Запись идёт **после** успешного ответа: отклонённый устройством тап (например `SecurityException: INJECT_EVENTS` на HyperOS) не должен попасть в сценарий.

- [ ] **Шаг 3: Взаимное исключение с инспектором и вкладками**

В `static/js/inspector.js` в начало `inspectorLoad()` (перед `const button = $('btnInsp')`, строка 38) добавить:

```javascript
    /* Инспектор морозит кадр и поглощает клики — записи нужен живой экран. */
    if (window.REC && REC.on) recPause();
```

В `static/js/app.js` заменить `showTab` (строки 12–18) на:

```javascript
/* Уход с вкладки «Инспектор» гасит режим: выключатель живёт внутри неё,
   а замороженный экран на других вкладках выглядит как зависший.
   Уход со «Сценариев» ставит запись на паузу по той же причине — шаги
   капали бы в невидимый список. */
function showTab(name) {
    if (name !== 'insp' && window.INSP && INSP.on) inspectorOff();
    if (name !== 'scen' && window.REC && REC.on) recPause();
    document.querySelectorAll('.tab').forEach(tab =>
        tab.classList.toggle('on', tab.dataset.pane === name));
    document.querySelectorAll('.pane').forEach(pane =>
        pane.classList.toggle('on', pane.id === 'pane-' + name));
}
```

- [ ] **Шаг 4: Ядро рекордера**

Создать `static/js/recorder.js`:

```javascript
'use strict';

/* Конструктор сценариев: запись действий, список шагов, сохранение.

   Дамп UI кэшируется вперёд — читается при старте записи и заново после
   каждого действия. Тап поэтому улетает на устройство мгновенно, а селектор
   берётся из кэша. См. docs/GOTCHAS.md.

   Состояние на window, а не const: у обычного (не module) скрипта
   верхнеуровневый const не становится свойством window. */

const REC_REFRESH_MS = 400;
const REC_PAUSE_MIN_S = 1.0;
const REC_DRAFT_KEY = 'farm.recorder.draft';

/* Типы действий /action → виды шагов. Действия shell тут нет намеренно:
   adb shell из вкладки «Устройство» это диагностика, а не шаг сценария. */
const REC_KIND = {
    tap: 'tap', long_tap: 'long_tap', swipe: 'swipe', text: 'type',
    key: 'key', unlock: 'unlock',
    launch: 'launch_app', stop: 'stop_app', url: 'open_url',
};

window.REC = {
    on: false,
    steps: [],
    nextId: 1,
    dump: null,
    stale: false,
    pauses: false,
    lastAt: 0,
    timer: null,
};

const REC = window.REC;

/* ------------------------------------------------------------------ режимы */

function recOpen() {
    $('scenList').style.display = 'none';
    $('scenBuild').style.display = 'flex';
    recRestore();
    recRender();
    recSync();
}

function recClose() {
    if (REC.on) recPause();
    $('scenBuild').style.display = 'none';
    $('scenList').style.display = 'flex';
}

function recSync() {
    const state = $('recState');
    if (state) {
        state.textContent = REC.on
            ? (REC.stale ? 'запись · обновляю…' : 'идёт запись')
            : (REC.steps.length ? 'пауза' : 'не записывается');
    }
    const start = $('btnRecStart');
    if (start) {
        start.classList.toggle('on', REC.on);
        start.disabled = REC.on;
    }
    if ($('btnRecPause')) $('btnRecPause').disabled = !REC.on;
    if ($('btnRecStop')) $('btnRecStop').disabled = !REC.on && !REC.steps.length;
}

function recBanner(message) {
    const box = $('recBanner');
    if (!box) return;
    box.textContent = message || '';
    box.style.display = message ? 'block' : 'none';
}

/* ------------------------------------------------------------------ запись */

async function recStart() {
    if (!S.active) {
        toast('сначала выберите устройство', 'bad');
        return;
    }
    if (window.INSP && INSP.on) inspectorOff();   // морозит кадр и глотает клики
    REC.on = true;
    REC.lastAt = Date.now();
    recSync();
    await recLoadDump();
    recSync();
}

function recPause() {
    REC.on = false;
    recOverlayOff();
    recSync();
    recSave();
}

function recStop() {
    recPause();
    if (REC.steps.length) toast(`записано шагов: ${REC.steps.length}`, 'ok');
}

async function recLoadDump() {
    if (!S.active) return;
    REC.stale = true;
    recOverlayOff();
    recSync();
    try {
        REC.dump = await api(`/api/devices/${S.active}/inspect`);
        recBanner(REC.dump.nodes.length
            ? ''
            : 'узлы не распознаны — шаги пишутся координатами. '
            + 'WebView, SurfaceView и игры не отдают дерево через accessibility.');
    } catch (e) {
        REC.dump = null;
        recBanner('снимок экрана не удался — шаги пишутся координатами: ' + e.message);
    }
    REC.stale = false;
    recOverlayRender();
    recSync();
}

function recRefreshDump() {
    clearTimeout(REC.timer);
    REC.stale = true;
    recOverlayOff();
    recSync();
    REC.timer = setTimeout(() => {
        if (REC.on) recLoadDump();
    }, REC_REFRESH_MS);
}

/* ------------------------------------------------------------------ шаги */

/* Наименьший по площади узел под точкой — тот же критерий, что в инспекторе. */
function recHit(x, y) {
    const nodes = (REC.dump && REC.dump.nodes) || [];
    let best = null, bestArea = Infinity;
    for (const node of nodes) {
        const [x1, y1, x2, y2] = node.bounds;
        if (x < x1 || x > x2 || y < y1 || y > y2) continue;
        const area = (x2 - x1) * (y2 - y1);
        if (area < bestArea) {
            bestArea = area;
            best = node;
        }
    }
    return best;
}

function recNodeLabel(node) {
    const name = node.text || node.description
        || (node.resourceId || '').split('/').pop();
    return name ? `«${name}»` : (node.class || '').split('.').pop();
}

function recLabel(step) {
    const a = step.args;
    switch (step.kind) {
        case 'click':
            return 'Тап по ' + (step.note || 'элементу');
        case 'tap':
            return `Тап ${a.x.toFixed(2)} × ${a.y.toFixed(2)}`;
        case 'long_tap':
            return `Долгое нажатие ${a.x.toFixed(2)} × ${a.y.toFixed(2)}`;
        case 'swipe':
            return `Свайп ${a.x1.toFixed(2)} × ${a.y1.toFixed(2)} → ${a.x2.toFixed(2)} × ${a.y2.toFixed(2)}`;
        case 'type':
            return (a.clear ? 'Очистить и ввести: ' : 'Ввод: ') + a.value;
        case 'key':
            return `Клавиша ${a.name}`;
        case 'unlock':
            return 'Разблокировать';
        case 'launch_app':
            return `Запуск ${a.package}`;
        case 'stop_app':
            return `Force-stop ${a.package}`;
        case 'open_url':
            return `Ссылка ${a.url}`;
        case 'sleep':
            return `Пауза ${a.seconds} с`;
        case 'screenshot':
            return 'Скриншот' + (a.name ? ` «${a.name}»` : '');
        default:
            return step.kind;
    }
}

function recPush(step) {
    step.id = REC.nextId++;
    step.param = step.param || null;
    step.note = step.note || '';
    step.warn = step.warn || '';
    REC.steps.push(step);
    REC.lastAt = Date.now();
    recRender();
    recSave();
    return step;
}

/* Пауза перед действием — только если её явно попросили галкой: ctx.click()
   и так ждёт элемент до 10 секунд, автопаузы просто зашумили бы код. */
function recAutoPause() {
    if (!REC.pauses || !REC.lastAt) return;
    const gap = (Date.now() - REC.lastAt) / 1000;
    if (gap < REC_PAUSE_MIN_S) return;
    recPush({kind: 'sleep', args: {seconds: Math.round(gap * 2) / 2}});
}

function recNoteTap(payload) {
    const node = recHit(payload.x, payload.y);
    const target = node ? REC.dump.nodes[node.target] : null;
    const selector = target && (target.selectors || [])[0];

    if (!selector || selector.call !== 'click') {
        recPush({kind: 'tap', args: {x: payload.x, y: payload.y}});
        return;
    }
    recPush({
        kind: 'click',
        args: {},
        selector: {call: selector.call, args: selector.args},
        alts: target.selectors,
        note: recNodeLabel(target),
        bounds: target.bounds,
        shot: REC.dump.screenshot,
        warn: selector.matches === 1 ? '' : `селектор неоднозначен: ${selector.matches}`,
    });
}

/* Живая клавиатура шлёт по символу — иначе «qwerty» это шесть строк кода. */
function recNoteType(payload) {
    const last = REC.steps[REC.steps.length - 1];
    if (last && last.kind === 'type' && !payload.clear && !last.args.clear) {
        last.args.value += payload.value;
        recRender();
        recSave();
        REC.lastAt = Date.now();
        return;
    }
    recPush({kind: 'type', args: {value: payload.value, clear: !!payload.clear}});
}

function recArgs(kind, p) {
    switch (kind) {
        case 'long_tap':
            return {x: p.x, y: p.y, duration: p.duration || 0.8};
        case 'swipe':
            return {x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2, duration: p.duration || 0.25};
        case 'key':
            return {name: p.name};
        case 'unlock':
            return {};
        case 'launch_app':
        case 'stop_app':
            return {package: p.package};
        case 'open_url':
            return {url: p.url};
        default:
            return {};
    }
}

function recNote(payload) {
    if (!REC.on) return;
    const kind = REC_KIND[payload.type];
    if (!kind) return;

    recAutoPause();
    const stale = REC.stale ? 'дамп устарел, проверь селектор' : '';

    if (kind === 'tap') {
        recNoteTap(payload);
        /* Дописываем к предупреждению об однозначности, а не затираем его:
           устаревший дамп и неоднозначный селектор — разные беды. */
        if (stale) {
            const last = REC.steps[REC.steps.length - 1];
            last.warn = last.warn ? `${last.warn}; ${stale}` : stale;
        }
    } else if (kind === 'type') {
        recNoteType(payload);
    } else {
        recPush({kind, args: recArgs(kind, payload)});
    }
    recRefreshDump();
}

function recAddSleep() {
    recPush({kind: 'sleep', args: {seconds: 1}});
}

function recAddShot() {
    recPush({kind: 'screenshot', args: {name: 'шаг' + REC.steps.length}});
}

/* ------------------------------------------------------------------ список */

function recRender() {
    const box = $('recSteps');
    if (!box) return;
    if (!REC.steps.length) {
        box.innerHTML = '<div class="empty">Шагов пока нет.<br>'
            + 'Нажмите «● Запись» и кликайте по экрану слева.</div>';
        return;
    }
    box.innerHTML = REC.steps.map(recRow).join('');
}

function recRow(step, index) {
    const warn = step.warn
        ? `<div class="rs-warn">⚠ ${esc(step.warn)}</div>`
        : (step.kind === 'click' ? '<div class="rs-ok">✓ уникален на экране</div>' : '');
    return `<div class="rs" data-id="${step.id}">
    <div class="rs-head">
      <span class="rs-n">${index + 1}</span>
      <span class="rs-label">${esc(recLabel(step))}</span>
    </div>
    ${warn}
  </div>`;
}

/* ------------------------------------------------------------------ черновик */

/* Миниатюры в localStorage не кладём: лимит 5 МБ выбирается десятком кадров. */
function recSave() {
    const light = REC.steps.map(step => Object.assign({}, step, {shot: null, alts: null}));
    try {
        localStorage.setItem(REC_DRAFT_KEY, JSON.stringify({steps: light, nextId: REC.nextId}));
    } catch (e) {
        /* переполнение хранилища не должно ронять запись */
    }
}

function recRestore() {
    if (REC.steps.length) return;
    let draft;
    try {
        draft = JSON.parse(localStorage.getItem(REC_DRAFT_KEY) || 'null');
    } catch (e) {
        return;
    }
    if (!draft || !draft.steps || !draft.steps.length) return;
    if (!confirm(`Восстановить черновик на ${draft.steps.length} шагов?`)) {
        localStorage.removeItem(REC_DRAFT_KEY);
        return;
    }
    REC.steps = draft.steps;
    REC.nextId = draft.nextId || (REC.steps.length + 1);
}

/* Заглушки: наполняются в задачах 8 и 9. */
function recOverlayOff() {}

function recOverlayRender() {}

function recPreview() {
    toast('предпросмотр появится в задаче 9', 'bad');
}

function recSaveForm() {
    toast('сохранение появится в задаче 9', 'bad');
}
```

- [ ] **Шаг 5: Проверить вручную**

Запустить: `./run.sh`, открыть <http://127.0.0.1:8777>, подключить устройство.

Проверить по пунктам:
1. Вкладка «Сценарии» показывает кнопку «✎ Создать сценарий записью». Нажатие переключает панель на конструктор, «← назад» возвращает список.
2. `● Запись` без выбранного устройства даёт красный тост «сначала выберите устройство».
3. С выбранным устройством `● Запись` меняет статус на «идёт запись», затем ненадолго на «запись · обновляю…».
4. Клик по экрану добавляет шаг вида «Тап по «Настройки»» и `✓ уникален на экране`; тап при этом реально прилетает на телефон.
5. Ввод текста в поле снизу даёт один шаг «Ввод: …»; при включённой «живой клавиатуре» набранное слово тоже остаётся **одним** шагом.
6. Кнопки «‹ Назад», «● Домой» дают шаги «Клавиша back», «Клавиша home».
7. На вкладке «Устройство» запуск пакета добавляет шаг «Запуск com.…».
8. Переключение на вкладку «Задачи» переводит статус в «пауза».
9. `+ пауза` и `+ скриншот` добавляют соответствующие шаги.
10. Включение инспектора во время записи гасит запись (кадр замирает, статус «пауза»).

---

### Задача 7: Ревью шагов

**Файлы:**
- Изменить: `static/js/recorder.js` (функции `recRow`, `recRender`, плюс новые)

**Интерфейсы:**
- Потребляет: `REC`, `recRender`, `recSave`, `recLabel` из задачи 6.
- Отдаёт: `recDelete(id)`, `recMove(id, delta)`, `recToggle(id)`, `recEditValue(id)`, `recPickSelector(id, index)`, `recParam(id)`, `recUnparam(id)`, `window.REC.params`. Задача 9 читает `REC.params` при сохранении.

- [ ] **Шаг 1: Хранилище параметров**

В `static/js/recorder.js` в объект `window.REC` добавить поля `params`, `open` и `hover`. `open` — какой шаг развёрнут в ревью, `hover` — узел под курсором, его читает оверлей из задачи 8:

```javascript
window.REC = {
    on: false,
    steps: [],
    params: {},
    open: null,
    hover: null,
    nextId: 1,
    dump: null,
    stale: false,
    pauses: false,
    lastAt: 0,
    timer: null,
};
```

В `recSave()` и `recRestore()` провести параметры вместе с шагами:

```javascript
function recSave() {
    const light = REC.steps.map(step => Object.assign({}, step, {shot: null, alts: null}));
    try {
        localStorage.setItem(REC_DRAFT_KEY, JSON.stringify(
            {steps: light, params: REC.params, nextId: REC.nextId}));
    } catch (e) {
        /* переполнение хранилища не должно ронять запись */
    }
}
```

и в `recRestore()` после присвоения шагов:

```javascript
    REC.steps = draft.steps;
    REC.params = draft.params || {};
    REC.nextId = draft.nextId || (REC.steps.length + 1);
```

- [ ] **Шаг 2: Развёрнутая строка шага**

Заменить `recRow` на набор функций:

```javascript
const REC_VALUE_KEY = {
    type: 'value', launch_app: 'package', stop_app: 'package',
    open_url: 'url', sleep: 'seconds', screenshot: 'name',
};

function recFind(id) {
    return REC.steps.find(step => step.id === Number(id));
}

function recCode(step) {
    if (step.kind === 'click') return `ctx.click(${step.selector.args})`;
    const key = REC_VALUE_KEY[step.kind];
    const value = key ? step.args[key] : '';
    if (step.param) return `ctx.${step.kind}(ctx.params["${step.param}"])`;
    return `ctx.${step.kind}(${value === '' || value === undefined ? '' : JSON.stringify(value)})`;
}

function recMark(step) {
    if (step.warn) return `<div class="rs-warn">⚠ ${esc(step.warn)}</div>`;
    if (step.kind === 'click') return '<div class="rs-ok">✓ уникален на экране</div>';
    return '';
}

function recAlts(step) {
    if (step.kind !== 'click' || !step.alts || step.alts.length < 2) return '';
    return '<div class="rs-alts">селектор:' + step.alts.map((alt, index) => `
      <label><input type="radio" name="sel${step.id}" ${alt.args === step.selector.args ? 'checked' : ''}
             onchange="recPickSelector(${step.id}, ${index})">
        ${alt.matches === 1 ? '✓' : '⚠' + alt.matches} ctx.${alt.call}(${esc(alt.args)})</label>`).join('') + '</div>';
}

function recValueEditor(step) {
    const key = REC_VALUE_KEY[step.kind];
    if (!key) return '';
    if (step.param) {
        return `<div class="rs-param">параметр <b>${esc(step.param)}</b>
      <button class="sm" onclick="recUnparam(${step.id})">вернуть значение</button></div>`;
    }
    const type = key === 'seconds' ? 'number' : 'text';
    return `<div class="row">
    <input type="${type}" step="any" value="${esc(step.args[key] ?? '')}"
           oninput="recEditValue(${step.id}, this.value)">
    <button class="sm" title="Вынести в параметры" onclick="recParam(${step.id})">{}</button>
  </div>`;
}

function recThumb(step) {
    if (!step.shot) return '';
    const frame = step.bounds
        ? `<div class="rs-box" style="left:${step.bounds[0] * 100}%;top:${step.bounds[1] * 100}%;
             width:${(step.bounds[2] - step.bounds[0]) * 100}%;
             height:${(step.bounds[3] - step.bounds[1]) * 100}%"></div>`
        : '';
    return `<div class="rs-thumb"><img src="${step.shot}" alt="">${frame}</div>`;
}

function recRow(step, index) {
    const open = REC.open === step.id;
    return `<div class="rs ${open ? 'open' : ''}">
    <div class="rs-head" onclick="recToggle(${step.id})">
      <span class="rs-n">${index + 1}</span>
      <span class="rs-label">${esc(recLabel(step))}</span>
      <span class="sp" style="flex:1"></span>
      <button class="sm" title="Выше" onclick="event.stopPropagation();recMove(${step.id},-1)">↑</button>
      <button class="sm" title="Ниже" onclick="event.stopPropagation();recMove(${step.id},1)">↓</button>
      <button class="sm danger" title="Удалить" onclick="event.stopPropagation();recDelete(${step.id})">⌫</button>
    </div>
    <div class="rs-code">${esc(recCode(step))}</div>
    ${recMark(step)}
    ${open ? recThumb(step) + recAlts(step) + recValueEditor(step) : ''}
  </div>`;
}
```

- [ ] **Шаг 3: Операции над шагами**

Дописать в `static/js/recorder.js` перед блоком «черновик»:

```javascript
function recToggle(id) {
    REC.open = REC.open === id ? null : id;
    recRender();
}

function recDelete(id) {
    REC.steps = REC.steps.filter(step => step.id !== id);
    recPrune();
    recRender();
    recSave();
}

function recMove(id, delta) {
    const index = REC.steps.findIndex(step => step.id === id);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= REC.steps.length) return;
    const [step] = REC.steps.splice(index, 1);
    REC.steps.splice(target, 0, step);
    recRender();
    recSave();
}

function recEditValue(id, value) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];
    step.args[key] = key === 'seconds' ? Number(value) || 0 : value;
    recSave();
}

function recPickSelector(id, index) {
    const step = recFind(id);
    const alt = step.alts[index];
    step.selector = {call: alt.call, args: alt.args};
    step.warn = alt.matches === 1 ? '' : `селектор неоднозначен: ${alt.matches}`;
    recRender();
    recSave();
}

function recParam(id) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];
    const name = (prompt('Имя параметра (латиница, нижний регистр):') || '').trim();
    if (!name) return;
    if (!/^[a-z][a-z0-9_]{0,31}$/.test(name)) {
        toast('имя параметра: латиница в нижнем регистре, цифры и _', 'bad');
        return;
    }
    const label = (prompt('Подпись в форме параметров:', name) || name).trim();
    REC.params[name] = {label, default: step.args[key]};
    step.param = name;
    recRender();
    recSave();
}

function recUnparam(id) {
    const step = recFind(id);
    const key = REC_VALUE_KEY[step.kind];
    const spec = REC.params[step.param];
    if (spec) step.args[key] = spec.default;
    step.param = null;
    recPrune();
    recRender();
    recSave();
}

/* Параметр без единого шага-владельца сервер отвергнет с 400. */
function recPrune() {
    const used = new Set(REC.steps.map(step => step.param).filter(Boolean));
    for (const name of Object.keys(REC.params)) {
        if (!used.has(name)) delete REC.params[name];
    }
}
```

- [ ] **Шаг 4: Проверить вручную**

Запустить `./run.sh`, записать 4–5 шагов и проверить:
1. Клик по строке шага разворачивает её: миниатюра с рамкой на тапнутом элементе, список селекторов-альтернатив, поле значения.
2. `↑`/`↓` переставляют шаг, номера пересчитываются.
3. `⌫` удаляет шаг, остальные остаются.
4. Выбор другого селектора у шага `click` меняет строку `ctx.click(...)` и метку `✓`/`⚠`.
5. Правка текста у шага «Ввод» меняет строку кода на лету.
6. `{}` спрашивает имя и подпись, строка становится `ctx.type(ctx.params["login"])`; «вернуть значение» откатывает.
7. Имя параметра `Логин` отвергается красным тостом.
8. Удаление единственного шага с параметром убирает параметр — проверить в консоли: `REC.params` пуст.

---

### Задача 8: Оверлей рамок поверх живого экрана

**Файлы:**
- Изменить: `static/index.html` (слой в `.stage`), `static/css/recorder.css`, `static/js/recorder.js` (`recOverlayOff`, `recOverlayRender`)

**Интерфейсы:**
- Потребляет: `REC.dump`, `recHit` из задачи 6.
- Отдаёт: рабочие `recOverlayOff()`, `recOverlayRender()`, `recOverlaySync()`.

Слой не перехватывает мышь (`pointer-events: none`) — этим он и отличается от инспектора: клик проходит на экран и реально тапает устройство.

- [ ] **Шаг 1: Слой в разметке**

В `static/index.html` в блоке `.stage` добавить `#recLayer` сразу после `#inspLayer`:

```html
        <div class="stage">
            <img id="screen" alt="">
            <div id="inspLayer"></div>
            <div id="recLayer"></div>
            <div class="empty" id="scrEmpty">Выберите устройство слева,<br>чтобы увидеть его экран.</div>
        </div>
```

- [ ] **Шаг 2: Стили**

Заменить содержимое `static/css/recorder.css` на:

```css
/* Конструктор сценариев: панель шагов и оверлей рамок. */

.mode { display: flex; flex-direction: column; flex: 1; min-height: 0; }

/* Слой рамок не перехватывает мышь: клик обязан дойти до экрана и тапнуть
   устройство. Этим режим записи и отличается от инспектора. */
#recLayer {
    position: absolute;
    display: none;
    pointer-events: none;
    z-index: 5;
}

#recLayer .rb {
    position: absolute;
    border: 1px solid rgba(120, 200, 255, .35);
}

#recLayer .rb.hov {
    border-color: var(--accent);
    background: rgba(120, 200, 255, .12);
}

/* строки шагов */
.rs { border-bottom: 1px solid var(--line); padding: 8px 10px; }
.rs-head { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.rs-n { color: var(--dim); font-size: 11px; min-width: 18px; }
.rs-label { font-size: 13px; }
/* overflow-wrap обязателен: resourceId вида com.android.systemui:id/… это одно
   «слово» без пробелов, и без переноса оно уезжает за правый край панели. */
.rs-code {
    color: var(--dim);
    font-family: ui-monospace, monospace;
    font-size: 11px;
    margin-top: 4px;
    overflow-wrap: anywhere;
}
.rs-ok { color: var(--ok); font-size: 11px; margin-top: 2px; }
.rs-warn { color: var(--warn); font-size: 11px; margin-top: 2px; }
.rs-alts { font-size: 11px; margin-top: 6px; display: flex; flex-direction: column; gap: 3px; }
.rs-alts label { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.rs-param { font-size: 11px; margin-top: 6px; display: flex; align-items: center; gap: 8px; }

/* inline-block обязателен: контейнер ужимается ровно по картинке, и рамка
   .rs-box, заданная в процентах, продолжает совпадать с элементом. Блок на всю
   ширину растянул бы систему координат, и рамка уехала бы. */
.rs-thumb { position: relative; display: inline-block; margin: 8px 0; }
.rs-thumb img {
    display: block;
    width: auto;
    height: auto;
    max-width: 160px;
    max-height: 200px;  /* у вертикального экрана телефона высота решает, а не ширина */
    border-radius: 4px;
}
.rs-box { position: absolute; border: 2px solid var(--accent); }
```

- [ ] **Шаг 3: Отрисовка слоя**

В `static/js/recorder.js` заменить заглушки `recOverlayOff` и `recOverlayRender` на:

```javascript
/* Слой позиционируется по прямоугольнику картинки, а не .stage: #screen
   центрируется во flex-контейнере и ужат max-width/max-height. Та же причина,
   что у inspSyncRect(). */
function recOverlaySync() {
    const layer = $('recLayer'), img = $('screen');
    if (!layer || !img) return;
    const image = img.getBoundingClientRect();
    const stage = img.parentElement.getBoundingClientRect();
    layer.style.left = (image.left - stage.left) + 'px';
    layer.style.top = (image.top - stage.top) + 'px';
    layer.style.width = image.width + 'px';
    layer.style.height = image.height + 'px';
}

function recOverlayOff() {
    const layer = $('recLayer');
    if (!layer) return;
    layer.style.display = 'none';
    layer.innerHTML = '';
}

function recOverlayRender() {
    const layer = $('recLayer');
    if (!layer) return;
    if (!REC.on || REC.stale || !REC.dump || !REC.dump.nodes.length) {
        recOverlayOff();
        return;
    }
    recOverlaySync();
    layer.style.display = 'block';
    layer.innerHTML = REC.dump.nodes
        .filter(node => node.text || node.resourceId || node.description)
        .map(node => {
            const [x1, y1, x2, y2] = node.bounds;
            const on = REC.hover === node.id ? ' hov' : '';
            return `<div class="rb${on}" style="left:${x1 * 100}%;top:${y1 * 100}%;`
                + `width:${(x2 - x1) * 100}%;height:${(y2 - y1) * 100}%"></div>`;
        })
        .join('');
}

/* Подсветка под курсором. Слушаем .stage, а не слой: у слоя выключена мышь,
   а узел #screen пересоздаётся при каждом startStream(). */
(function initRecorderHover() {
    const stage = document.querySelector('.stage');
    if (!stage) return;

    stage.addEventListener('mousemove', ev => {
        if (!REC.on || REC.stale) return;
        const rect = $('screen').getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const hit = recHit((ev.clientX - rect.left) / rect.width,
            (ev.clientY - rect.top) / rect.height);
        const id = hit ? hit.id : null;
        if (id !== REC.hover) {
            REC.hover = id;
            recOverlayRender();
        }
    });

    stage.addEventListener('mouseleave', () => {
        if (REC.hover != null) {
            REC.hover = null;
            recOverlayRender();
        }
    });

    if (window.ResizeObserver) new ResizeObserver(recOverlaySync).observe(stage);
    window.addEventListener('resize', recOverlaySync);
})();
```

- [ ] **Шаг 4: Проверить вручную**

Запустить `./run.sh` и проверить:
1. После `● Запись` поверх живого экрана появляются голубые рамки именованных элементов, экран продолжает двигаться.
2. Наведение курсора подсвечивает элемент под ним.
3. Клик по элементу **и** тапает устройство, **и** добавляет шаг — рамки не мешают.
4. Сразу после клика рамки исчезают, статус «запись · обновляю…», затем рамки возвращаются уже для нового экрана.
5. Пауза и «← назад» гасят рамки.
6. Переключение вкладок в правой колонке не сдвигает рамки относительно картинки.

---

### Задача 9: Предпросмотр кода, сохранение, управление своими сценариями

**Файлы:**
- Изменить: `static/js/recorder.js` (`recPreview`, `recSaveForm`, транслит), `static/js/scenarios.js` (`scenarioCard`, удаление)

**Интерфейсы:**
- Потребляет: `POST /api/recorder/preview`, `POST /api/recorder/save`, `DELETE /api/scenarios/{key}` из задачи 5; `REC.steps`, `REC.params` из задач 6–7; модальное окно (`#modal`, `#mTitle`, `#mBody`, `#mActs`, `closeModal()`) из `device-modal.js`.
- Отдаёт: `recPayload()`, `recPreview()`, `recSaveForm()`, `recSubmit()`, `recSlug(name)`, `deleteScenario(key)`.

- [ ] **Шаг 1: Тело запроса и предпросмотр**

В `static/js/recorder.js` заменить заглушку `recPreview` на:

```javascript
/* На сервер уезжает только то, что нужно генератору: миниатюры,
   альтернативы селекторов и метки уникальности остаются в браузере. */
function recPayload(meta) {
    return {
        meta: meta,
        params: REC.params,
        steps: REC.steps.map(step => ({
            kind: step.kind,
            args: step.args,
            selector: step.selector || null,
            param: step.param || null,
            note: step.kind === 'click' ? step.note : '',
        })),
    };
}

function recMeta() {
    return {
        name: ($('recName') && $('recName').value.trim()) || 'Записанный сценарий',
        description: ($('recDesc') && $('recDesc').value.trim()) || '',
        watch_popups: !$('recPopups') || $('recPopups').checked,
    };
}

async function recPreview() {
    if (!REC.steps.length) {
        toast('ещё нет ни одного шага', 'bad');
        return;
    }
    try {
        const source = await api('/api/recorder/preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(recPayload(recMeta())),
        });
        $('mTitle').textContent = 'Сгенерированный код';
        $('mBody').innerHTML = `<pre class="log" style="max-height:60vh">${esc(source)}</pre>`;
        $('mActs').innerHTML = '<span class="sp" style="flex:1"></span>'
            + '<button class="sm" onclick="closeModal()">Закрыть</button>';
        $('modal').classList.add('on');
    } catch (e) {
        toast(e.message, 'bad');
    }
}
```

- [ ] **Шаг 2: Транслит и форма сохранения**

Дописать туда же:

```javascript
const REC_TRANSLIT = {
    а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z',
    и: 'i', й: 'y', к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r',
    с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch',
    ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
};

/* Имя файла — подсказка, не защита: ключ всё равно проверяется на сервере. */
function recSlug(name) {
    const latin = String(name).toLowerCase().split('')
        .map(ch => (ch in REC_TRANSLIT ? REC_TRANSLIT[ch] : ch)).join('');
    const key = latin.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 48);
    return /^[a-z]/.test(key) ? key : ('s_' + key).slice(0, 48);
}

function recSaveForm() {
    if (!REC.steps.length) {
        toast('ещё нет ни одного шага', 'bad');
        return;
    }
    if (REC.on) recPause();

    $('mTitle').textContent = 'Сохранить сценарий';
    $('mBody').innerHTML = `
    <div class="row"><label>Название</label>
      <input type="text" id="recName" value="Записанный сценарий"
             oninput="$('recKey').value = recSlug(this.value)"></div>
    <div class="row"><label>Имя файла</label>
      <input type="text" id="recKey" value="${esc(recSlug('Записанный сценарий'))}"></div>
    <div class="row"><label>Описание</label>
      <input type="text" id="recDesc" placeholder="что делает сценарий"></div>
    <div class="row"><label class="kb">
      <input type="checkbox" id="recPopups" checked style="accent-color:var(--accent)">
      закрывать всплывающие диалоги (ctx.watch_popups)</label></div>`;
    $('mActs').innerHTML = '<span class="sp" style="flex:1"></span>'
        + '<button class="sm" onclick="closeModal()">Отмена</button>'
        + '<button class="primary" onclick="recSubmit(false)">Сохранить</button>';
    $('modal').classList.add('on');
}

async function recSubmit(overwrite) {
    const key = $('recKey').value.trim();
    const body = recPayload(recMeta());
    body.key = key;
    body.overwrite = !!overwrite;

    try {
        await post('/api/recorder/save', body);
    } catch (e) {
        if (!overwrite && /уже существует/.test(e.message)) {
            if (confirm(`Файл ${key}.py уже есть. Перезаписать?`)) recSubmit(true);
            return;
        }
        toast(e.message, 'bad');
        return;
    }

    closeModal();
    REC.steps = [];
    REC.params = {};
    REC.open = null;
    localStorage.removeItem(REC_DRAFT_KEY);
    recRender();
    recSync();
    recClose();
    toast('сценарий сохранён', 'ok');
    await loadScenarios(true);
    pickScenario(key);
}
```

- [ ] **Шаг 3: Значок и удаление в списке**

В `static/js/scenarios.js` заменить `scenarioCard` (строки 21–29) на:

```javascript
function scenarioCard(scenario) {
    const lastErrorLine = String(scenario.error || '').split('\n').filter(Boolean).pop();
    const mark = scenario.recorded ? '<span class="rec-mark" title="Записано конструктором">✒</span> ' : '';
    const drop = scenario.recorded
        ? `<button class="sm danger" title="Удалить сценарий"
             onclick="event.stopPropagation();deleteScenario('${scenario.key}')">⌫</button>`
        : '';
    return `<div class="sc ${S.scenario === scenario.key ? 'on' : ''}"
               onclick="pickScenario('${scenario.key}')">
    <div class="nm">${mark}${esc(scenario.name)}${drop}</div>
    ${scenario.description ? `<div class="ds">${esc(scenario.description)}</div>` : ''}
    ${scenario.error ? `<div class="er">${esc(lastErrorLine)}</div>` : ''}
  </div>`;
}

async function deleteScenario(key) {
    if (!confirm(`Удалить сценарий «${key}»? Файл scenarios/${key}.py будет стёрт.`)) return;
    try {
        await api('/api/scenarios/' + encodeURIComponent(key), {method: 'DELETE'});
        toast('сценарий удалён', 'ok');
        if (S.scenario === key) S.scenario = null;
        await loadScenarios(true);
    } catch (e) {
        toast(e.message, 'bad');
    }
}
```

Дописать в `static/css/recorder.css`:

```css
.rec-mark { color: var(--accent); }
.sc .nm { display: flex; align-items: center; gap: 6px; }
.sc .nm .sm { margin-left: auto; }
```

- [ ] **Шаг 4: Проверить вручную**

Запустить `./run.sh` и пройти путь целиком:
1. Записать 5–6 шагов, включая ввод текста и запуск приложения.
2. `⟨⟩ код` открывает модалку с исходником: шапка `"""Записано конструктором фермы …"""`, `RECORDED = True`, тело `run(ctx)` с шагами по порядку.
3. Вынести текст в параметр, снова открыть код — там `ctx.params["…"]` и блок `PARAMS`.
4. `💾 Сохранить`: название по-русски, имя файла заполняется транслитом автоматически.
5. После сохранения панель возвращается к списку, новый сценарий выбран, помечен `✒`, у него видна форма параметров с подписью, которую задали.
6. Запустить сохранённый сценарий на устройстве — он проходит.
7. Повторное сохранение с тем же именем файла спрашивает «Перезаписать?».
8. `⌫` у записанного сценария удаляет его; у встроенного `open_app` кнопки удаления нет.
9. Перезагрузить страницу с незавершённой записью — предлагается восстановить черновик, шаги возвращаются (без миниатюр).

---

### Задача 10: Документация

**Файлы:**
- Изменить: `README.md` (после раздела «Визуальный инспектор», строка 79), `docs/GOTCHAS.md`

- [ ] **Шаг 1: Раздел в README**

Вставить в `README.md` после раздела «Визуальный инспектор» и перед «Свои сценарии»:

```markdown
## Конструктор сценариев

Вкладка «Сценарии» → **«✎ Создать сценарий записью»**. Кнопка «● Запись»
запоминает всё, что вы делаете с устройством: тапы, свайпы, ввод текста,
клавиши, запуск приложений со вкладки «Устройство».

Клик в режиме записи делает три вещи разом: тапает устройство, подсвечивает
найденный элемент рамкой и добавляет шаг с готовым селектором. Метка `✓` у шага
означает, что селектор однозначен, `⚠3` — что под него подходят три узла: тогда
разверните шаг и выберите другой вариант.

Список шагов справа — это и есть ревью. Шаг можно удалить, переставить,
поменять у него значение или селектор, развернуть и увидеть миниатюру момента с
рамкой на цели. Кнопка `{}` выносит значение в `PARAMS` — дальше сценарий
запускается на двадцати устройствах с разными данными.

«⟨⟩ код» показывает, что сгенерировалось. «💾 Сохранить» кладёт файл в
`scenarios/`, и он сразу появляется в списке со значком `✒`. Записанные
сценарии можно удалить прямо из списка; встроенные — нельзя.

Дальше это обычный `.py`-файл: правьте его в редакторе. Обратно в конструктор
он не открывается.

Запись и инспектор взаимоисключающие: инспектор замораживает кадр и поглощает
клики, записи нужен живой экран. Включение одного гасит другое.

Там, где не распознаются узлы — `WebView`, `SurfaceView`, игры — шаги пишутся
координатами (`ctx.tap(x, y)`). Это ограничение Android, а не фермы.
```

- [ ] **Шаг 2: Пункт в GOTCHAS**

Дописать в `docs/GOTCHAS.md` в раздел «Бэкенд» (или создать раздел «Конструктор» в конце файла):

```markdown
### `static/js/recorder.js` — дамп кэшируется вперёд, а не читается перед тапом

Очевидный вариант — на каждый клик снять дамп, найти узел и только потом
тапнуть. Он добавляет 0.5–1.5 с к каждому клику, и ручная работа становится
вязкой до неюзабельности.

Поэтому дамп читается при старте записи и заново после каждого действия, а клик
делает hit-test по кэшу. Плата — клик, сделанный быстрее цикла обновления,
попадает на устаревший дамп; такой шаг помечается `⚠ дамп устарел`. Между двумя
кликами человека проходит больше секунды, так что на практике это редкость.

### `static/js/recorder.js` — запись после ответа сервера, а не до

`recNote()` вызывается из `act()` только после успешного ответа
`/api/devices/{serial}/action`. На HyperOS/MIUI без тумблера «USB-отладка
(настройки безопасности)» тап отклоняется с `SecurityException: INJECT_EVENTS`.
Записать шаг, которого на устройстве не произошло, — значит собрать сценарий,
который не воспроизводится.

### `static/css/recorder.css` — `#recLayer` не перехватывает мышь

У слоя рамок `pointer-events: none`, в отличие от `#inspLayer`. Инспектор
клики поглощает намеренно (наблюдение не меняет состояние телефона), а записи
клик обязан дойти до `#screen` и реально тапнуть устройство. Убрать это
свойство — сломать весь режим: шаги будут писаться, а телефон стоять.
```

- [ ] **Шаг 3: Проверить**

Запустить: `.venv/bin/python -m pytest -q`
Ожидание: `49 passed`.

Открыть README и убедиться, что новый раздел стоит между «Визуальный инспектор» и «Свои сценарии», а раздел «Структура» по-прежнему описывает дерево (он уже расходится с реальностью — `farm/devices.py`, `farm/u2pool.py` и прочие имена устарели после разбиения на пакеты; правка структуры выходит за рамки этой задачи, но `farm/recorder/` в неё стоит дописать при первом же касании).

---

## Самопроверка плана

**Покрытие спеки:**

| Требование спеки | Задача |
|---|---|
| Кэш-дамп вперёд, обновление после действия | 6 |
| Набор действий v1 (жесты, текст, клавиши, launch/stop/url, sleep, screenshot) | 1, 2, 6 |
| Шаги в браузере, кодген на сервере | 1, 2, 6 |
| Ручная параметризация | 1, 2, 7 |
| Одноразовая генерация, без round-trip | 4, 9 |
| Конструктор внутри вкладки «Сценарии» | 6 |
| Клик тапает + подсвечивает + пишет шаг | 6, 8 |
| Инспектор и запись взаимоисключающие | 6 |
| Ревью: удалить, переставить, править, миниатюра, альтернативы селектора | 7 |
| Слипание текста | 6 |
| Галка «писать паузы» | 6 |
| Таблица генерации, шапка файла, `RECORDED` | 2, 3 |
| Границы параметризации (селекторы не выносятся) | 1 |
| Эндпоинты preview/save/delete | 5 |
| Валидация ключа, защита пути, 409 | 4, 5 |
| Значок `✒` и удаление своих | 3, 9 |
| Ошибки: нет устройства, пустой дамп, отвал, `matches > 1`, устаревший дамп, черновик | 6, 7, 9 |
| Тесты кодгена, интеграционный импорт, схема, save, delete | 1–5 |
| README и GOTCHAS | 10 |

**Согласованность имён:** `recNote`, `recPush`, `recRender`, `recSave`, `recSync`, `recOverlayRender`, `recOverlayOff`, `REC_VALUE_KEY`, `recFind` — определены в задаче 6 и используются под теми же именами в 7–9. `steps.normalize_step` возвращает ровно `{kind, args, selector, param, note}` — эту форму потребляют `codegen._call` (задача 2), `save.save` (задача 4) и `recPayload` (задача 9).

**Известное расхождение:** `recPayload` шлёт `note` только для шагов `click`. Это осознанно — комментарий у `ctx.key("back")` дублировал бы саму строку.
