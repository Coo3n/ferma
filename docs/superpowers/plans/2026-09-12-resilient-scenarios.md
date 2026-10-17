# Устойчивые сценарии — план имплементации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Четыре слоя устойчивости сценариев — стабильность экрана, стражи, многослойный резолвер (селекторы → текст → OCR → шаблон → координаты), якоря экранов — по спеке `docs/superpowers/specs/2026-09-12-resilient-scenarios-design.md`.

**Architecture:** Устойчивость живёт под капотом `ctx` (farm/context.py) и в новых модулях `farm/control/stability.py`, `farm/guards.py`, `farm/resolve.py`, `farm/vision/`. Рекордер (steps/codegen/save) учится новым полям шага. Vision-зависимости опциональны: без них слои OCR и шаблонов выключены, остальное работает как сейчас.

**Tech Stack:** Python 3.11+, FastAPI, uiautomator2, Pillow; опционально opencv-python-headless, numpy, ocrmac (macOS) / pytesseract.

## Global Constraints

- **Без git.** Пользователь работает без репозитория — никаких commit-шагов. Вместо коммита каждая задача заканчивается прогоном полного набора тестов.
- **Команда тестов:** `.venv/bin/python -m pytest tests/ -q` (полный набор), `.venv/bin/python -m pytest tests/test_X.py -v` (точечно). Все команды — из корня проекта `/Users/hlamov.ilya/Desktop/android-farm`.
- **Базовая линия на 12.09.2026: 156 тестов, 0.62 с, всё зелёное.** После каждой задачи число тестов растёт, падений быть не должно.
- **Устройство для тестов не нужно** — правило проекта (docs/GOTCHAS.md, заголовки farm/ui/tree.py и farm/recorder/steps.py). Чистая логика не знает про adb, FastAPI и файловую систему; adb-зависимое подменяется в тестах.
- **Тесты называются по-русски**, как весь проект: `def test_стабильность_после_двух_одинаковых_дампов():`. Докстринги и комментарии — по-русски; заголовок модуля объясняет «почему», а не «что».
- **requirements.txt не меняется.** Vision-зависимости — только в новом `requirements-vision.txt`, импорты ленивые. Сейчас cv2/numpy/ocrmac/pytesseract **не установлены**: vision-тесты обязаны пропускаться (SKIP), а не падать.
- **Координаты — нормализованные 0..1** везде: `ctx.tap` принимает такие (farm/control/geometry.py `to_pixels`), `tree.parse` отдаёт такие.
- **Обратная совместимость:** старые сценарии и старые записи конструктора остаются валидными, новые поля шагов опциональны.

**Вне рамок этого плана:** фронтенд рекордера (`static/js/recorder.js` — вырезание кропов, вставка expect-шагов при записи, отрисовка новых шагов). Это следующий план: бэкенд-API из задач 11–14 полностью готов принимать данные от клиента, а `ctx.click_target` / `ctx.expect_screen` полезны уже в рукописных сценариях.

---

## Этап 1 — стабильность + стражи

### Task 1: Стабильность экрана — `farm/control/stability.py`

**Files:**
- Modify: `farm/config.py` (после `ARTIFACT_MAX_WIDTH`, строка ~48)
- Create: `farm/control/stability.py`
- Modify: `farm/control/__init__.py`
- Test: `tests/test_stability.py`

**Interfaces:**
- Consumes: `farm.control.diagnostics.dump_hierarchy(serial) -> str`.
- Produces: `control.wait_stable(serial, timeout=None, quiet=None, dump=None, sleep=time.sleep) -> bool`; `config.SETTLE: bool`, `config.SETTLE_TIMEOUT: float`, `config.SETTLE_QUIET: float`. Task 2 зовёт `wait_stable` из `ctx._settle()`.

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_stability.py
"""Стабильность экрана: два одинаковых дампа подряд. Устройство не нужно —
dump и sleep подменяются аргументами."""
import itertools

from farm.control import stability


def test_стабильность_после_двух_одинаковых_дампов():
    dumps = iter(["<a/>", "<b/>", "<b/>"])
    assert stability.wait_stable(
        "x", timeout=5, quiet=0, dump=lambda: next(dumps), sleep=lambda s: None,
    ) is True


def test_вечная_анимация_даёт_таймаут():
    counter = itertools.count()
    assert stability.wait_stable(
        "x", timeout=0.05, quiet=0, dump=lambda: str(next(counter)),
        sleep=lambda s: None,
    ) is False


def test_упавший_дамп_не_роняет_шаг():
    def boom():
        raise RuntimeError("adb упал")

    assert stability.wait_stable(
        "x", timeout=1, quiet=0, dump=boom, sleep=lambda s: None,
    ) is False
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/bin/python -m pytest tests/test_stability.py -v`
Expected: FAIL — `ImportError: cannot import name 'stability' from 'farm.control'`

- [ ] **Step 3: Конфиг**

В `farm/config.py` после строки `ARTIFACT_MAX_WIDTH = ...`:

```python
# Стабильность экрана: перед шагом ждём два одинаковых дампа подряд. Вечная
# анимация стабильности не даст — тогда выходим по таймауту и шаг идёт дальше:
# ожидание best-effort, а не гейт.
SETTLE = os.getenv("FARM_SETTLE", "1") != "0"
SETTLE_TIMEOUT = float(os.getenv("FARM_SETTLE_TIMEOUT", "3.0"))
SETTLE_QUIET = float(os.getenv("FARM_SETTLE_QUIET", "0.4"))
```

- [ ] **Step 4: Модуль**

```python
# farm/control/stability.py
"""Ожидание, пока экран дорисуется.

Медленный девайс не успел отрисовать экран — клик уходит в пустоту. Два
одинаковых дампа иерархии подряд означают «дорисовано». dump и sleep
подменяются в тестах, поэтому модуль проверяется без устройства.
"""
from __future__ import annotations

import hashlib
import time

from .. import config
from .diagnostics import dump_hierarchy


def _fingerprint(xml: str) -> str:
    return hashlib.md5(xml.encode("utf-8", "replace")).hexdigest()


def wait_stable(serial: str, timeout: float | None = None,
                quiet: float | None = None, dump=None, sleep=time.sleep) -> bool:
    """True — экран стабилен; False — таймаут или дамп не снялся."""
    timeout = config.SETTLE_TIMEOUT if timeout is None else timeout
    quiet = config.SETTLE_QUIET if quiet is None else quiet
    dump = dump or (lambda: dump_hierarchy(serial))
    deadline = time.monotonic() + timeout
    try:
        last = _fingerprint(dump())
    except Exception:  # noqa: BLE001 — дамп не снялся, шагу не мешаем
        return False
    while time.monotonic() < deadline:
        sleep(quiet)
        try:
            current = _fingerprint(dump())
        except Exception:  # noqa: BLE001
            return False
        if current == last:
            return True
        last = current
    return False
```

В `farm/control/__init__.py`: добавить `from .stability import wait_stable` к остальным импортам и `"wait_stable"` в `__all__`.

- [ ] **Step 5: Тесты зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/test_stability.py -v` → 3 PASS.
Run: `.venv/bin/python -m pytest tests/ -q` → 159 passed.

---

### Task 2: `ctx._settle()` перед жестами

**Files:**
- Modify: `farm/context.py` (`__init__` ~строка 46; `type` :127; `click` :160; `click_any` :173; `set_text` :237)
- Test: `tests/test_context_resilience.py` (новый)

**Interfaces:**
- Consumes: `control.wait_stable`, `config.SETTLE`.
- Produces: `ctx.settle: bool` (по умолчанию True), `ctx._settle() -> None`. Задачи 5, 10, 13 используют и патчат `_settle`.

- [ ] **Step 1: Падающие тесты**

```python
# tests/test_context_resilience.py
"""Устойчивость ctx: стабильность экрана, стражи, многослойные цели, якоря.
Устройство не нужно: поиск элементов и жесты подменяются."""
import pytest

from farm import config, control
from farm.context import DeviceContext, StepFailed


class ФейкЭлемент:
    def __init__(self):
        self.clicked = 0

    def click(self):
        self.clicked += 1


def ctx_():
    return DeviceContext("test-serial", logger=lambda m: None)


def test_settle_зовёт_wait_stable(monkeypatch):
    ctx = ctx_()
    calls = []
    monkeypatch.setattr(control, "wait_stable", lambda serial: calls.append(serial))
    monkeypatch.setattr(config, "SETTLE", True)
    ctx._settle()
    assert calls == ["test-serial"]


def test_флаг_сценария_выключает_settle(monkeypatch):
    ctx = ctx_()
    calls = []
    monkeypatch.setattr(control, "wait_stable", lambda serial: calls.append(serial))
    monkeypatch.setattr(config, "SETTLE", True)
    ctx.settle = False
    ctx._settle()
    assert calls == []


def test_click_ждёт_стабильности_до_поиска(monkeypatch):
    ctx = ctx_()
    order = []
    monkeypatch.setattr(ctx, "_settle", lambda: order.append("settle"))
    el = ФейкЭлемент()
    monkeypatch.setattr(ctx, "find",
                        lambda timeout=10, **sel: order.append("find") or el)
    ctx.click(text="Войти")
    assert order == ["settle", "find"]
    assert el.clicked == 1
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/python -m pytest tests/test_context_resilience.py -v`
Expected: FAIL — `AttributeError: 'DeviceContext' object has no attribute '_settle'`

- [ ] **Step 3: Имплементация**

В `DeviceContext.__init__`, после `self.human = False`:

```python
        self.settle = True
```

Новый метод рядом с `_pre_action`:

```python
    def _settle(self) -> None:
        """Дождаться, пока экран дорисуется, прежде чем искать цель."""
        if self.settle and config.SETTLE:
            control.wait_stable(self.serial)
```

Вставить `self._settle()` в начало тела (сразу после `self.check_cancel()`, где он есть) в методах: `type`, `click`, `click_any`, `set_text`.

- [ ] **Step 4: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 162 passed.

---

### Task 3: Движок стражей — `farm/guards.py`

**Files:**
- Modify: `farm/config.py` (после `ARTIFACTS_DIR`, и `mkdir` в конце файла)
- Create: `farm/guards.py`
- Test: `tests/test_guards.py`

**Interfaces:**
- Consumes: `config.GUARDS_DIR`; от ctx — только утиные методы `exists(timeout, **sel)`, `click_if_exists(timeout, **sel)`, `key(name)`, `current_app()`, `log(msg)`.
- Produces: `guards.Guard`, `guards.load(package="") -> list[Guard]`, `guards.GuardEngine().try_all(ctx) -> list[str]` (имена сработавших). Task 5 кладёт `GuardEngine` в ctx.

- [ ] **Step 1: Падающие тесты**

```python
# tests/test_guards.py
"""Стражи: загрузка файлов, срабатывание, лимиты. Экран — фейковый ctx."""
import json

import pytest

from farm import config, guards


class ФейкCtx:
    """Экран — список «видимых» селекторов. Клик убирает попап с экрана."""

    def __init__(self, screen, app=""):
        self.screen = list(screen)
        self.app = app
        self.actions = []
        self.lines = []

    def exists(self, timeout=0, **sel):
        return sel in self.screen

    def click_if_exists(self, timeout=0, **sel):
        if sel in self.screen:
            self.screen.remove(sel)
            self.actions.append(("click", sel))
            return True
        return False

    def key(self, name):
        self.actions.append(("key", name))

    def current_app(self):
        return self.app

    def log(self, message):
        self.lines.append(message)


ПОПАП = {
    "name": "permission-ru",
    "when": {"any": [{"text": "Разрешить"}]},
    "action": {"click": {"text": "Разрешить"}},
}


def записать(dirpath, name, data):
    (dirpath / name).write_text(json.dumps(data, ensure_ascii=False), "utf-8")


@pytest.fixture
def guards_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GUARDS_DIR", tmp_path)
    guards._cache.clear()
    return tmp_path


def test_страж_срабатывает_и_докладывает(guards_dir):
    записать(guards_dir, "global.json", [ПОПАП])
    ctx = ФейкCtx(screen=[{"text": "Разрешить"}])
    assert guards.GuardEngine().try_all(ctx) == ["permission-ru"]
    assert ctx.actions == [("click", {"text": "Разрешить"})]


def test_max_fires_обрывает_цикл(guards_dir):
    записать(guards_dir, "global.json", [dict(ПОПАП, max_fires=2)])
    engine = guards.GuardEngine()
    for ожидаемо in (["permission-ru"], ["permission-ru"], []):
        assert engine.try_all(ФейкCtx(screen=[{"text": "Разрешить"}])) == ожидаемо


def test_страж_пакета_молчит_в_чужом_приложении(guards_dir):
    записать(guards_dir, "global.json", [])
    записать(guards_dir, "com.example.json", [{
        "name": "rate-us",
        "when": {"any": [{"textContains": "Оцени"}]},
        "action": {"key": "back"},
    }])
    экран = [{"textContains": "Оцени"}]
    assert guards.GuardEngine().try_all(ФейкCtx(экран, app="com.other")) == []
    ctx = ФейкCtx(экран, app="com.example")
    assert guards.GuardEngine().try_all(ctx) == ["rate-us"]
    assert ctx.actions == [("key", "back")]


def test_битый_страж_пропускается_годный_остаётся(guards_dir):
    записать(guards_dir, "global.json", [
        {"name": "без-действия", "when": {"any": [{"text": "x"}]}},
        ПОПАП,
    ])
    assert [g.name for g in guards.load()] == ["permission-ru"]


def test_битый_json_даёт_пустой_список(guards_dir):
    (guards_dir / "global.json").write_text("{битый", "utf-8")
    assert guards.load() == []


def test_отсутствие_файла_не_ошибка(guards_dir):
    assert guards.load("com.нет.такого") == []
```

- [ ] **Step 2: Убедиться, что падают**

Run: `.venv/bin/python -m pytest tests/test_guards.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'farm.guards'`

- [ ] **Step 3: Конфиг**

В `farm/config.py` после `ARTIFACTS_DIR = ...`:

```python
GUARDS_DIR = Path(os.getenv("FARM_GUARDS_DIR", ROOT / "guards"))
```

И в конце файла, рядом с существующими `mkdir`:

```python
GUARDS_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Модуль**

```python
# farm/guards.py
"""Стражи — известные перехватчики: «если на экране X, нажми Y и продолжай».

Файлы guards/global.json (всегда) и guards/<package>.json (когда пакет на
экране), горячая перезагрузка по mtime, как у сценариев. Битый файл или битый
страж пропускаются с предупреждением: ферму они не роняют.

Модуль не знает про adb — экран он видит через утиный ctx
(exists/click_if_exists/key/current_app/log), поэтому тестируется на фейке.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from . import config

log = logging.getLogger("farm.guards")

DEFAULT_MAX_FIRES = 3   # потолок срабатываний одного стража за прогон
PROBE_TIMEOUT = 0.5     # сек на проверку одного признака when
ACTION_TIMEOUT = 1.5    # сек на поиск цели действия


@dataclass
class Guard:
    name: str
    when: list          # u2-селекторы; страж срабатывает по любому из них
    action: dict        # {"click": селектор} | {"key": имя клавиши}
    max_fires: int
    source: str


class GuardError(ValueError):
    """Страж не проходит проверку — пропускается с предупреждением."""


def _parse_guard(raw, source: str) -> Guard:
    if not isinstance(raw, dict):
        raise GuardError(f"{source}: страж должен быть объектом")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise GuardError(f"{source}: у стража нет имени")
    when = (raw.get("when") or {}).get("any")
    if (not isinstance(when, list) or not when
            or not all(isinstance(s, dict) and s for s in when)):
        raise GuardError(f"{source}/{name}: when.any — непустой список селекторов")
    action = raw.get("action")
    if (not isinstance(action, dict) or len(action) != 1
            or next(iter(action)) not in ("click", "key")):
        raise GuardError(f"{source}/{name}: action — ровно одно из click|key")
    if "click" in action and not (isinstance(action["click"], dict) and action["click"]):
        raise GuardError(f"{source}/{name}: action.click — непустой селектор")
    if "key" in action and not (isinstance(action["key"], str) and action["key"]):
        raise GuardError(f"{source}/{name}: action.key — имя клавиши")
    max_fires = raw.get("max_fires", DEFAULT_MAX_FIRES)
    if not isinstance(max_fires, int) or isinstance(max_fires, bool) or max_fires < 1:
        raise GuardError(f"{source}/{name}: max_fires — целое ≥ 1")
    return Guard(name=name, when=when, action=action,
                 max_fires=max_fires, source=source)


_cache: dict[str, tuple[float, list]] = {}


def _load_file(path: Path) -> list:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    cached = _cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    out = []
    try:
        raw = json.loads(path.read_text("utf-8"))
        if not isinstance(raw, list):
            raise GuardError(f"{path.name}: ожидается список стражей")
        for item in raw:
            try:
                out.append(_parse_guard(item, path.stem))
            except GuardError as e:
                log.warning("страж пропущен: %s", e)
    except (OSError, json.JSONDecodeError, GuardError) as e:
        log.warning("файл стражей %s не читается: %s", path.name, e)
        out = []
    _cache[str(path)] = (mtime, out)
    return out


def load(package: str = "") -> list:
    """global.json плюс <package>.json, если пакет задан."""
    root = Path(config.GUARDS_DIR)
    found = list(_load_file(root / "global.json"))
    if package:
        found += _load_file(root / f"{package}.json")
    return found


class GuardEngine:
    """Счётчики срабатываний. Живёт один прогон задачи — внутри ctx."""

    def __init__(self) -> None:
        self._fired: dict[str, int] = {}

    def try_all(self, ctx) -> list[str]:
        try:
            package = ctx.current_app()
        except Exception:  # noqa: BLE001 — без пакета работают глобальные
            package = ""
        fired = []
        for guard in load(package):
            if self._fired.get(guard.name, 0) >= guard.max_fires:
                continue
            if not any(ctx.exists(timeout=PROBE_TIMEOUT, **sel) for sel in guard.when):
                continue
            if self._apply(ctx, guard):
                self._fired[guard.name] = self._fired.get(guard.name, 0) + 1
                fired.append(guard.name)
                ctx.log(f"страж «{guard.name}» сработал")
        return fired

    @staticmethod
    def _apply(ctx, guard) -> bool:
        if "click" in guard.action:
            return bool(ctx.click_if_exists(timeout=ACTION_TIMEOUT,
                                            **guard.action["click"]))
        ctx.key(guard.action["key"])
        return True
```

- [ ] **Step 5: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 168 passed.

---

### Task 4: Комплект стражей по умолчанию — `guards/global.json`

**Files:**
- Create: `guards/global.json`
- Test: `tests/test_guards.py` (дописать)

**Interfaces:**
- Consumes: формат из Task 3.
- Produces: файл, который грузится целиком, без пропусков.

- [ ] **Step 1: Падающий тест**

Дописать в `tests/test_guards.py`:

```python
def test_комплект_из_коробки_грузится_целиком():
    """Дефолтный global.json обязан пройти проверку весь, без пропусков."""
    guards._cache.clear()
    path = config.ROOT / "guards" / "global.json"
    raw = json.loads(path.read_text("utf-8"))
    loaded = guards._load_file(path)
    assert len(loaded) == len(raw) >= 4
    assert len({g.name for g in loaded}) == len(loaded)
```

Run: `.venv/bin/python -m pytest tests/test_guards.py::test_комплект_из_коробки_грузится_целиком -v`
Expected: FAIL — файла нет (`FileNotFoundError`).

- [ ] **Step 2: Файл `guards/global.json`**

```json
[
  {
    "name": "permission-allow-id",
    "when": {"any": [{"resourceId": "com.android.permissioncontroller:id/permission_allow_button"}]},
    "action": {"click": {"resourceId": "com.android.permissioncontroller:id/permission_allow_button"}},
    "max_fires": 5
  },
  {
    "name": "permission-allow-ru",
    "when": {"any": [{"text": "Разрешить"}, {"text": "РАЗРЕШИТЬ"}]},
    "action": {"click": {"text": "Разрешить"}},
    "max_fires": 5
  },
  {
    "name": "permission-allow-en",
    "when": {"any": [{"text": "Allow"}, {"text": "ALLOW"}]},
    "action": {"click": {"text": "Allow"}},
    "max_fires": 5
  },
  {
    "name": "permission-while-using",
    "when": {"any": [{"text": "While using the app"}, {"text": "При использовании приложения"}]},
    "action": {"click": {"textMatches": "(?i).*(using the app|использовании приложения).*"}},
    "max_fires": 5
  },
  {
    "name": "anr-wait",
    "when": {"any": [{"textContains": "не отвечает"}, {"textContains": "isn't responding"}]},
    "action": {"click": {"text": "Подождать"}}
  },
  {
    "name": "rate-us-back",
    "when": {"any": [{"textContains": "Оцените приложение"}, {"textContains": "Rate this app"}]},
    "action": {"key": "back"},
    "max_fires": 2
  }
]
```

Замечание для реализующего: у `permission-while-using` и признак, и клик покрывают обе локали — клик через `textMatches` с регуляркой (uiautomator2 такой селектор поддерживает). Если бы клик ловил только английский вариант, на русской локали страж молча не срабатывал бы.

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 169 passed.

---

### Task 5: Стражи в путях падения ctx

**Files:**
- Modify: `farm/context.py` (импорты, `__init__`, `click` :160, `click_any` :173, `set_text` :237, новый `_rescue`)
- Test: `tests/test_context_resilience.py` (дописать)

**Interfaces:**
- Consumes: `guards.GuardEngine` из Task 3.
- Produces: `ctx._rescue() -> bool`. Task 10 (`click_target`) и Task 13 (`expect_screen`) зовут его при промахе; тесты подменяют `ctx._guards`.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_context_resilience.py`:

```python
class МолчащиеСтражи:
    def try_all(self, ctx):
        return []


class СпасающиеСтражи:
    """Изображает стража, закрывшего попап: после вызова цель находится."""

    def __init__(self, state):
        self.state = state

    def try_all(self, ctx):
        self.state["rescued"] = True
        return ["фейковый-страж"]


def test_страж_спасает_промахнувшийся_click(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "_scroll_to", lambda **sel: None)
    el, state = ФейкЭлемент(), {"rescued": False}
    monkeypatch.setattr(ctx, "find",
                        lambda timeout=10, **sel: el if state["rescued"] else None)
    ctx._guards = СпасающиеСтражи(state)
    ctx.click(timeout=0.1, text="Далее")
    assert el.clicked == 1


def test_молчащие_стражи_не_мешают_падению(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "_scroll_to", lambda **sel: None)
    monkeypatch.setattr(ctx, "find", lambda timeout=10, **sel: None)
    ctx._guards = МолчащиеСтражи()
    with pytest.raises(StepFailed):
        ctx.click(timeout=0.1, text="Далее")


def test_упавшие_стражи_не_роняют_сценарий():
    ctx = ctx_()

    class Бомба:
        def try_all(self, c):
            raise RuntimeError("стражи сломались")

    ctx._guards = Бомба()
    assert ctx._rescue() is False
```

Run: `.venv/bin/python -m pytest tests/test_context_resilience.py -v`
Expected: новые FAIL (`_rescue` нет; click падает, не спасаясь).

- [ ] **Step 2: Имплементация**

`farm/context.py` — импорт: `from . import adb, config, control, guards`.

В `__init__` после `self.settle = True`:

```python
        self._guards = guards.GuardEngine()
```

Новый метод рядом с `retry`:

```python
    def _rescue(self) -> bool:
        """Шаг промахнулся — дать стражам закрыть перехватчик. True, если был толк."""
        try:
            return bool(self._guards.try_all(self))
        except Exception as e:  # noqa: BLE001 — стражи не должны ронять сценарий
            self.log(f"стражи упали: {e}")
            return False
```

В `click` — между поиском и `fail`:

```python
        if el is None and self._rescue():
            el = self.find(timeout=5, **selector)
            if el is None and scroll:
                el = self._scroll_to(**selector)
        if el is None:
            self.fail(f"не найден элемент {selector} за {timeout} с")
```

В `click_any` — перед финальным `self.fail(...)`:

```python
        if self._rescue():
            for sel in selectors:
                el = self.find(timeout=1.5, **sel)
                if el is not None:
                    self._click_el(el)
                    return
        self.fail(f"не найден ни один из селекторов {list(selectors)} за {timeout} с")
```

В `set_text` — перед `self.fail(...)`:

```python
        if el is None and self._rescue():
            el = self.find(timeout=5, **selector)
        if el is None:
            self.fail(f"не найдено поле ввода {selector}")
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 172 passed.

---

## Этап 2 — резолвер

### Task 6: Синонимы и сопоставление текста

**Files:**
- Create: `farm/vision/__init__.py`, `farm/vision/synonyms.py`
- Create: `farm/resolve.py` (пока только сопоставление текста)
- Test: `tests/test_resolver.py`

**Interfaces:**
- Produces: `synonyms.expand(text: str) -> set[str]` (casefold-нормализация); `resolve.match_text(items, wanted) -> tuple[str, float, float] | None`, где `items` — список `(текст, cx, cy)` с нормализованными координатами. Task 9 использует оба.

- [ ] **Step 1: Падающие тесты**

```python
# tests/test_resolver.py
"""Резолвер: сопоставление текста и порядок слоёв. Устройство не нужно."""
import pytest

from farm import resolve
from farm.vision import synonyms


def test_синонимы_работают_в_обе_стороны():
    assert "allow" in synonyms.expand("Разрешить")
    assert "разрешить" in synonyms.expand("ALLOW")
    assert synonyms.expand("нечто уникальное") == {"нечто уникальное"}


ЭЛЕМЕНТЫ = [("Вход в аккаунт", 0.5, 0.2), ("Войти", 0.5, 0.8), ("Отмена", 0.5, 0.9)]


def test_точное_совпадение_бьёт_вхождение():
    assert resolve.match_text(ЭЛЕМЕНТЫ, ["Войти"]) == ("Войти", 0.5, 0.8)


def test_вхождение_когда_точного_нет():
    assert resolve.match_text(ЭЛЕМЕНТЫ, ["Вход"]) == ("Вход в аккаунт", 0.5, 0.2)


def test_совпадение_по_синониму():
    assert resolve.match_text([("Allow", 0.5, 0.7)], ["Разрешить"]) == ("Allow", 0.5, 0.7)


def test_шум_ocr_переживается_нормализацией_гомоглифов():
    # латинская «o» вместо кириллической — типичная ошибка распознавания
    assert resolve.match_text([("Вoйти", 0.5, 0.8)], ["Войти"]) == ("Вoйти", 0.5, 0.8)


def test_вход_не_путается_с_выходом():
    """Ключевой тест безопасности: «Войти» и «Выйти» нельзя перепутать.

    difflib даёт «войти»/«вoйти» (шум OCR) и «войти»/«выйти» (разные
    действия!) одинаковые 0.8 — порогом их не разделить. Разделяет
    нормализация гомоглифов: шум схлопывается в точное совпадение, а
    «Выйти» остаётся за порогом нечёткости.
    """
    assert resolve.match_text([("Выйти", 0.5, 0.8)], ["Войти"]) is None


def test_далёкий_текст_не_совпадает():
    assert resolve.match_text([("Настройки", 0.5, 0.5)], ["Войти"]) is None
```

Run: `.venv/bin/python -m pytest tests/test_resolver.py -v` → FAIL (модулей нет).

- [ ] **Step 2: Имплементация**

```python
# farm/vision/__init__.py
"""Зрение фермы: OCR и поиск по шаблону. Все тяжёлые импорты ленивые."""
```

```python
# farm/vision/synonyms.py
"""Синонимы типовых кнопок ru/en: на MIUI «Разрешить», на Samsung «Allow».

Без них текстовый селектор, записанный на одном устройстве, промахивается на
устройстве с другой локалью.
"""
from __future__ import annotations

PAIRS = [
    ("разрешить", "allow"), ("далее", "next"), ("продолжить", "continue"),
    ("пропустить", "skip"), ("принять", "accept"), ("ок", "ok"),
    ("готово", "done"), ("войти", "log in"), ("отмена", "cancel"),
    ("закрыть", "close"), ("начать", "get started"), ("понятно", "got it"),
]

_INDEX: dict[str, set[str]] = {}
for _a, _b in PAIRS:
    _INDEX.setdefault(_a, {_a}).add(_b)
    _INDEX.setdefault(_b, {_b}).add(_a)


def expand(text: str) -> set[str]:
    """Нормализованный текст плюс его синонимы на другом языке."""
    key = " ".join(text.casefold().split())
    return set(_INDEX.get(key, {key}))
```

```python
# farm/resolve.py
"""Многослойный резолвер цели: селекторы → текст → OCR → шаблон → координаты.

Здесь чистое сопоставление и порядок слоёв. Экран резолвер видит только через
ctx, поэтому проверяется на фейке, без устройства.
"""
from __future__ import annotations

import difflib

from .vision import synonyms

FUZZY_RATIO = 0.85

# OCR путает кириллицу с визуально неотличимой латиницей: «Вoйти» с латинской
# «o» перестаёт совпадать с «Войти». Приводим обе стороны к одному алфавиту ДО
# сравнения. Понизить вместо этого порог нечёткости нельзя: difflib даёт
# «войти»/«вoйти» (шум) и «войти»/«выйти» (ВХОД против ВЫХОДА) одинаковые 0.8 —
# порогом эти случаи не разделяются, а ценой ошибки будет выход из аккаунта.
# В таблице только по-настоящему неотличимые пары; «b/в», «h/н» и прочие
# похожие-но-различимые сюда не входят.
HOMOGLYPHS = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х",
})


def _norm(text: str) -> str:
    return " ".join((text or "").casefold().translate(HOMOGLYPHS).split())


def match_text(items, wanted):
    """Первый подходящий (текст, cx, cy): точное → вхождение → нечёткое."""
    variants = set()
    for w in wanted:
        variants |= synonyms.expand(w)
    normed = [(_norm(t), (t, x, y)) for t, x, y in items if _norm(t)]
    for exact in (True, False):
        for norm, item in normed:
            for v in variants:
                if (norm == v) if exact else (v in norm):
                    return item
    best = None
    for norm, item in normed:
        for v in variants:
            ratio = difflib.SequenceMatcher(None, v, norm).ratio()
            if ratio >= FUZZY_RATIO and (best is None or ratio > best[0]):
                best = (ratio, item)
    return best[1] if best else None
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 178 passed.

---

### Task 7: OCR-бэкенды — `farm/vision/ocr.py`

**Files:**
- Create: `farm/vision/ocr.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces: `ocr.Box(text, cx, cy, conf)` — центр в нормализованных 0..1; `ocr.backend() -> str` (`"vision"` | `"tesseract"` | `""`); `ocr.ocr(image_bytes) -> list[Box]`. Task 9 зовёт `ocr.ocr`, когда `ocr.backend()` непуст.

**Важно:** vision-зависимостей в окружении нет — `backend()` вернёт `""`, распознающий тест пропустится (SKIP). Это правильный результат задачи, а не недоделка.

- [ ] **Step 1: Падающие тесты**

```python
# tests/test_vision.py
"""Golden-тесты зрения. Пропускаются, когда vision-зависимости не стоят."""
import io

import pytest

from farm.vision import ocr


def шрифт(size=48):
    """Настоящий шрифт, если он есть: дефолтный битмап OCR распознаёт плохо."""
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def картинка_с_текстом(text="Login", size=(400, 160)):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((40, 50), text, fill="black", font=шрифт())
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_бэкенд_всегда_отвечает_строкой():
    assert isinstance(ocr.backend(), str)


def test_без_бэкенда_ocr_возвращает_пусто(monkeypatch):
    monkeypatch.setattr(ocr, "_backend", "")
    assert ocr.ocr(b"whatever") == []  # только ASCII: в bytes-литерале кириллица запрещена


@pytest.mark.skipif(not ocr.backend(), reason="OCR-бэкенд не установлен")
def test_ocr_находит_нарисованный_текст():
    boxes = ocr.ocr(картинка_с_текстом("Login"))
    hits = [b for b in boxes if "login" in b.text.casefold()]
    assert hits, f"OCR не нашёл текст: {boxes}"
    assert 0.0 < hits[0].cx < 1.0 and 0.0 < hits[0].cy < 1.0
```

Run: `.venv/bin/python -m pytest tests/test_vision.py -v` → FAIL (модуля нет).

- [ ] **Step 2: Имплементация**

```python
# farm/vision/ocr.py
"""OCR: Apple Vision на macOS (пакет ocrmac), tesseract запасным.

Бэкенд выбирается один раз и лениво. Без зависимостей ферма работает — просто
слой OCR в резолвере выключен.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass


@dataclass
class Box:
    text: str
    cx: float   # центр, нормализованный 0..1
    cy: float
    conf: float


_backend: str | None = None  # None — ещё не выбирали; "" — ничего нет


def backend() -> str:
    global _backend
    if _backend is None:
        _backend = ""
        if sys.platform == "darwin":
            try:
                from ocrmac import ocrmac  # noqa: F401
                _backend = "vision"
            except ImportError:
                pass
        if not _backend:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                _backend = "tesseract"
            except Exception:  # noqa: BLE001 — нет пакета или самого бинаря
                pass
    return _backend


def ocr(image_bytes: bytes) -> list:
    name = backend()
    if name == "vision":
        return _vision(image_bytes)
    if name == "tesseract":
        return _tesseract(image_bytes)
    return []


def _vision(image_bytes: bytes) -> list:
    from ocrmac import ocrmac
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    out = []
    # ocrmac отдаёт (text, confidence, (x, y, w, h)); bbox нормализован, начало
    # координат — левый НИЖНИЙ угол (так устроен Vision framework).
    for text, conf, (x, y, w, h) in ocrmac.OCR(image).recognize():
        out.append(Box(text=text, cx=x + w / 2, cy=1 - (y + h / 2), conf=float(conf)))
    return out


def _tesseract(image_bytes: bytes) -> list:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(image, lang="rus+eng",
                                     output_type=pytesseract.Output.DICT)
    out = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        cx = (data["left"][i] + data["width"][i] / 2) / image.width
        cy = (data["top"][i] + data["height"][i] / 2) / image.height
        out.append(Box(text=text, cx=cx, cy=cy, conf=conf / 100.0))
    return out
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/test_vision.py -v`
Expected: 2 passed, 1 skipped («OCR-бэкенд не установлен»).
Run: `.venv/bin/python -m pytest tests/ -q` → 180 passed, 1 skipped.

Если позже поставишь `ocrmac` и распознающий тест упадёт на распаковке кортежа — сверься с установленной версией (`.venv/bin/python -c "from ocrmac import ocrmac; help(ocrmac.OCR.recognize)"`) и поправь распаковку в `_vision`. Тест для того и написан.

---

### Task 8: Поиск по шаблону — `farm/vision/template.py`

**Files:**
- Create: `farm/vision/template.py`
- Test: `tests/test_vision.py` (дописать)

**Interfaces:**
- Produces: `template.available() -> bool`; `template.THRESHOLD`; `template.find(screen_png, template_png, base_scale=1.0) -> tuple[float, float, float] | None` — (cx, cy, score), центры нормализованные. Task 9 зовёт при `available()`.

**Важно:** opencv не установлен — все три распознающих теста пропустятся (SKIP). Это ожидаемый результат.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_vision.py`:

```python
from farm.vision import template


def png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def экран_и_кроп(scale=1.0):
    """Синтетика: «кнопка» на сером фоне; кроп кнопки — шаблон."""
    from PIL import Image, ImageDraw
    screen = Image.new("RGB", (400, 800), (200, 200, 200))
    draw = ImageDraw.Draw(screen)
    draw.rectangle((150, 500, 250, 560), fill=(30, 90, 200))
    draw.ellipse((180, 515, 220, 545), fill=(250, 220, 40))
    crop = screen.crop((150, 500, 250, 560))
    if scale != 1.0:
        screen = screen.resize((int(400 * scale), int(800 * scale)))
    return png(screen), png(crop)


def test_available_всегда_отвечает_булевым():
    assert isinstance(template.available(), bool)


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_шаблон_найден_на_том_же_масштабе():
    screen, crop = экран_и_кроп()
    hit = template.find(screen, crop)
    assert hit is not None
    cx, cy, score = hit
    assert abs(cx - 0.5) < 0.03 and abs(cy - 530 / 800) < 0.03
    assert score >= template.THRESHOLD


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_шаблон_найден_на_другом_разрешении():
    screen, crop = экран_и_кроп(scale=1.2)
    hit = template.find(screen, crop, base_scale=1.2)
    assert hit is not None and abs(hit[0] - 0.5) < 0.03


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_отсутствующий_шаблон_даёт_None():
    from PIL import Image
    _, crop = экран_и_кроп()
    assert template.find(png(Image.new("RGB", (400, 800), "white")), crop) is None
```

Run: `.venv/bin/python -m pytest tests/test_vision.py -v` → ERROR при импорте (модуля нет).

- [ ] **Step 2: Имплементация**

```python
# farm/vision/template.py
"""Поиск кропа на экране: OpenCV matchTemplate на нескольких масштабах.

Базовый масштаб — отношение ширины экрана прогона к ширине экрана записи (его
даёт meta.json папки ассетов). Вокруг базового перебираются ×0.85, ×1.0, ×1.15,
диапазон обрезан 0.7–1.3: дальше начинается мусор.
"""
from __future__ import annotations

SCALE_STEPS = (0.85, 1.0, 1.15)
SCALE_MIN, SCALE_MAX = 0.7, 1.3
THRESHOLD = 0.85
MIN_SIDE = 8  # шаблон меньше 8 px после масштабирования ищет что попало


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def find(screen_png: bytes, template_png: bytes, base_scale: float = 1.0):
    """(cx, cy, score) в нормализованных координатах — или None."""
    import cv2
    import numpy as np

    screen = cv2.imdecode(np.frombuffer(screen_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    original = cv2.imdecode(np.frombuffer(template_png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if screen is None or original is None:
        return None
    best = None
    for step in SCALE_STEPS:
        scale = min(max(base_scale * step, SCALE_MIN), SCALE_MAX)
        w = int(original.shape[1] * scale)
        h = int(original.shape[0] * scale)
        if w < MIN_SIDE or h < MIN_SIDE or w > screen.shape[1] or h > screen.shape[0]:
            continue
        tpl = cv2.resize(original, (w, h), interpolation=cv2.INTER_AREA)
        _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(screen, tpl,
                                                           cv2.TM_CCOEFF_NORMED))
        if score >= THRESHOLD and (best is None or score > best[2]):
            best = ((loc[0] + w / 2) / screen.shape[1],
                    (loc[1] + h / 2) / screen.shape[0],
                    float(score))
    return best
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 181 passed, 4 skipped.

---

### Task 9: Слои резолвера — `farm/resolve.py`

**Files:**
- Modify: `farm/resolve.py`
- Test: `tests/test_resolver.py` (дописать)

**Interfaces:**
- Consumes: `farm.ui.tree.parse(xml, width, height) -> list[Node]` (сигнатура сверена; `Node` даёт `.text`, `.description`, `.bounds` в долях 0..1); `vision.ocr`, `vision.template`, `resolve.match_text`; от ctx — `find`, `size`, `dump_hierarchy()`, `screen_bytes()`, `asset(name) -> (bytes | None, float)`, `check_cancel()` (появятся в Task 10; в тестах — фейк).
- Produces: `resolve.Hit(x, y, layer, detail)`; `resolve.resolve(ctx, sel=None, text=None, img=None, at=None, timeout=10.0) -> Hit | None`. Слои: `"selector"`, `"tree-text"`, `"ocr"`, `"template"`, `"point"`. Task 10 зовёт из `ctx.click_target`.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_resolver.py`:

```python
ДАМП = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node text="Войти" resource-id="" class="android.widget.Button"
        content-desc="" bounds="[100,700][300,780]" />
  <node text="" resource-id="" class="android.widget.TextView"
        content-desc="Настройки" bounds="[0,0][100,80]" />
</hierarchy>"""


class ФейкЭлемент:
    info = {"bounds": {"left": 400, "top": 400, "right": 600, "bottom": 500}}


class ФейкCtx:
    def __init__(self, found=None, dump="<hierarchy/>", shot=b"", asset=(None, 1.0)):
        self.found = found
        self.dump = dump
        self.shot = shot
        self._asset = asset
        self.size = (1000, 2000)
        self.lines = []

    def find(self, timeout=10, **sel):
        return self.found

    def dump_hierarchy(self):
        return self.dump

    def screen_bytes(self):
        return self.shot

    def asset(self, name):
        return self._asset

    def check_cancel(self):
        pass

    def log(self, message):
        self.lines.append(message)


def test_слой_селекторов_выигрывает():
    hit = resolve.resolve(ФейкCtx(found=ФейкЭлемент(), dump=ДАМП),
                          sel=[dict(text="Войти")], text=["Войти"], timeout=0.1)
    assert hit.layer == "selector"
    assert (hit.x, hit.y) == (0.5, 0.225)   # центр bounds, делённый на размер экрана


def test_текст_дерева_когда_селекторы_мимо():
    hit = resolve.resolve(ФейкCtx(dump=ДАМП), sel=[dict(resourceId="нет")],
                          text=["Войти"], timeout=0.1)
    assert hit.layer == "tree-text"
    assert abs(hit.x - 0.2) < 0.01 and abs(hit.y - 0.37) < 0.01


def test_ocr_когда_дерево_пустое(monkeypatch):
    from farm.vision import ocr
    monkeypatch.setattr(ocr, "backend", lambda: "vision")
    monkeypatch.setattr(ocr, "ocr", lambda b: [ocr.Box("Войти", 0.5, 0.6, 0.95)])
    hit = resolve.resolve(ФейкCtx(shot=b"png"), text=["Войти"], timeout=0.1)
    assert hit.layer == "ocr" and (hit.x, hit.y) == (0.5, 0.6)


def test_слой_шаблона(monkeypatch):
    from farm.vision import template
    monkeypatch.setattr(template, "available", lambda: True)
    monkeypatch.setattr(template, "find", lambda s, t, base_scale=1.0: (0.3, 0.7, 0.9))
    ctx = ФейкCtx(shot=b"png", asset=(b"crop", 1.0))
    hit = resolve.resolve(ctx, img="07_login.png", timeout=0.1)
    assert hit.layer == "template" and (hit.x, hit.y) == (0.3, 0.7)


def test_координаты_последний_резерв():
    assert resolve.resolve(ФейкCtx(), at=(0.5, 0.9), timeout=0.1).layer == "point"


def test_цель_не_найдена_ничем():
    assert resolve.resolve(ФейкCtx(), sel=[dict(text="x")], timeout=0.1) is None


def test_пустая_цель_отвергается():
    with pytest.raises(ValueError):
        resolve.resolve(ФейкCtx(), timeout=0.1)
```

Run: `.venv/bin/python -m pytest tests/test_resolver.py -v` → новые FAIL.

- [ ] **Step 2: Имплементация**

Дописать в `farm/resolve.py` (импорты — к существующим наверху файла):

```python
import time
from dataclasses import dataclass

from .ui import tree
from .vision import ocr as ocr_mod
from .vision import template as tpl_mod


@dataclass(frozen=True)
class Hit:
    x: float
    y: float
    layer: str
    detail: str = ""


def resolve(ctx, sel=None, text=None, img=None, at=None, timeout: float = 10.0):
    """Первый сработавший слой.

    Дерево (селекторы и текст) крутится до таймаута — экран может дорисоваться.
    Зрение пробуется по разу: оно дорогое, а повторный снимок того же экрана
    ничего не добавит.
    """
    sel = list(sel or ())
    text = list(text or ())
    if not (sel or text or img or at):
        raise ValueError("пустая цель: нужен хотя бы один слой")

    deadline = time.time() + timeout
    while sel or text:   # без этих слоёв круг только жёг бы процессор
        ctx.check_cancel()
        for s in sel:
            el = ctx.find(timeout=1.0, **s)
            if el is not None:
                center = _center(el, ctx.size)
                if center:
                    return Hit(center[0], center[1], "selector", str(s))
        if text:
            hit = _by_tree_text(ctx, text)
            if hit:
                return hit
        if time.time() >= deadline:
            break

    if text and ocr_mod.backend():
        hit = _by_ocr(ctx, text)
        if hit:
            return hit
    if img:
        hit = _by_template(ctx, img)
        if hit:
            return hit
    if at:
        return Hit(float(at[0]), float(at[1]), "point")
    return None


def _center(el, size):
    try:
        b = el.info["bounds"]
        w, h = size
        return ((b["left"] + b["right"]) / 2 / w, (b["top"] + b["bottom"]) / 2 / h)
    except Exception:  # noqa: BLE001 — элемент испарился, слой считается промахом
        return None


def _by_tree_text(ctx, wanted):
    try:
        w, h = ctx.size
        nodes = tree.parse(ctx.dump_hierarchy(), w, h)
    except Exception:  # noqa: BLE001 — дамп не снялся
        return None
    items = []
    for node in nodes:
        label = (node.text or node.description or "").strip()
        if label:
            items.append((label,
                          (node.bounds[0] + node.bounds[2]) / 2,
                          (node.bounds[1] + node.bounds[3]) / 2))
    found = match_text(items, wanted)
    return Hit(found[1], found[2], "tree-text", found[0]) if found else None


def _by_ocr(ctx, wanted):
    try:
        boxes = ocr_mod.ocr(ctx.screen_bytes())
    except Exception:  # noqa: BLE001 — OCR не должен ронять шаг
        return None
    found = match_text([(b.text, b.cx, b.cy) for b in boxes], wanted)
    return Hit(found[1], found[2], "ocr", found[0]) if found else None


def _by_template(ctx, img):
    if not tpl_mod.available():
        return None
    data, base_scale = ctx.asset(img)
    if not data:
        return None
    try:
        found = tpl_mod.find(ctx.screen_bytes(), data, base_scale=base_scale)
    except Exception:  # noqa: BLE001
        return None
    if found:
        return Hit(found[0], found[1], "template", f"{img} score={found[2]:.2f}")
    return None
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 188 passed, 4 skipped.

---

### Task 10: `ctx.click_target`, ассеты, runner

**Files:**
- Modify: `farm/context.py` (импорты, `__init__`, новые методы)
- Modify: `farm/devices/runner.py:123-130` (конструктор DeviceContext)
- Test: `tests/test_context_resilience.py` (дописать)

**Interfaces:**
- Consumes: `resolve.resolve`, `resolve.Hit`, `control.screenshot(serial, max_width=None, quality=...) -> bytes` (farm/control/capture.py).
- Produces: `DeviceContext(..., scenario_assets: Path | None = None)`; `ctx.screen_bytes() -> bytes`; `ctx.asset(name) -> tuple[bytes | None, float]`; `ctx.click_target(sel=None, text=None, img=None, at=None, timeout=10) -> None`. Task 11 генерит вызовы `click_target`, Task 13 использует `asset`.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_context_resilience.py` (наверх файла — `import json` и `from farm import resolve`):

```python
def test_click_target_тапает_найденную_точку(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    taps = []
    monkeypatch.setattr(ctx, "tap", lambda x, y: taps.append((x, y)))
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "ocr", "Войти"))
    ctx.click_target(text=["Войти"])
    assert taps == [(0.5, 0.6)]


def test_запасной_слой_попадает_в_журнал(monkeypatch):
    lines = []
    ctx = DeviceContext("s", logger=lines.append)
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "tap", lambda x, y: None)
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "ocr", "Войти"))
    ctx.click_target(text=["Войти"])
    assert any("ocr" in line for line in lines)


def test_слой_селекторов_журнал_не_засоряет(monkeypatch):
    lines = []
    ctx = DeviceContext("s", logger=lines.append)
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "tap", lambda x, y: None)
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "selector", ""))
    ctx.click_target(sel=[dict(text="Войти")])
    assert lines == []


def test_click_target_зовёт_стражей_и_падает(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(resolve, "resolve", lambda c, **kw: None)
    ctx._guards = МолчащиеСтражи()
    with pytest.raises(StepFailed):
        ctx.click_target(sel=[dict(text="x")], timeout=0.1)


def test_ассет_отдаёт_байты_и_масштаб(monkeypatch, tmp_path):
    assets = tmp_path / "demo_assets"
    assets.mkdir()
    (assets / "07_login.png").write_bytes("png-байты".encode("utf-8")  # bytes-литерал кириллицу не принимает)
    (assets / "meta.json").write_text(json.dumps({"screen_width": 500}), "utf-8")
    # size — property, поэтому подменяется на классе, а не на экземпляре
    monkeypatch.setattr(DeviceContext, "size", property(lambda self: (1000, 2000)))
    ctx = DeviceContext("s", logger=lambda m: None, scenario_assets=assets)
    assert ctx.asset("07_login.png") == ("png-байты".encode("utf-8")  # bytes-литерал кириллицу не принимает, 2.0)
    assert ctx.asset("нет.png") == (None, 1.0)


def test_без_папки_ассетов_масштаб_единица():
    ctx = DeviceContext("s", logger=lambda m: None)
    assert ctx.asset("07_login.png") == (None, 1.0)
```

Run: `.venv/bin/python -m pytest tests/test_context_resilience.py -v` → новые FAIL.

- [ ] **Step 2: Имплементация**

`farm/context.py` — импорты: добавить `import json` и расширить `from . import adb, config, control, guards, resolve`.

`__init__`: новый параметр `scenario_assets: Path | None = None` (последним, после `device_name`), в теле — `self.scenario_assets = scenario_assets`.

Новые методы после `text_on_screen`:

```python
    def screen_bytes(self) -> bytes:
        """Свежий JPEG экрана для слоёв зрения."""
        return control.screenshot(self.serial, quality=85)

    def asset(self, name: str) -> tuple[bytes | None, float]:
        """Байты ассета записи и базовый масштаб (ширина сейчас ÷ при записи)."""
        if not self.scenario_assets:
            return None, 1.0
        path = Path(self.scenario_assets) / name
        if not path.is_file():
            return None, 1.0
        base = 1.0
        try:
            meta = json.loads(
                (Path(self.scenario_assets) / "meta.json").read_text("utf-8"))
            width = float(meta.get("screen_width") or 0)
            if width > 0:
                base = self.size[0] / width
        except (OSError, ValueError):
            pass
        return path.read_bytes(), base

    def click_target(self, sel=None, text=None, img=None, at=None,
                     timeout: float = 10) -> None:
        """Клик по многослойной цели: селекторы → текст → OCR → шаблон → точка."""
        self.check_cancel()
        self._settle()
        hit = resolve.resolve(self, sel=sel, text=text, img=img, at=at,
                              timeout=timeout)
        if hit is None and self._rescue():
            hit = resolve.resolve(self, sel=sel, text=text, img=img, at=at,
                                  timeout=5)
        if hit is None:
            self.fail(f"цель не найдена ни одним слоем: "
                      f"sel={sel} text={text} img={img} at={at}")
        if hit.layer != "selector":
            self.log(f"цель найдена слоем «{hit.layer}» ({hit.detail}) — "
                     f"селекторы не совпали, пора обновить сценарий")
        self.tap(hit.x, hit.y)
```

`farm/devices/runner.py` — в конструктор `DeviceContext` (строки 123–130) добавить аргумент:

```python
            scenario_assets=Path(sc.path).with_name(f"{Path(sc.path).stem}_assets"),
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 194 passed, 4 skipped.

---

### Task 11: Новые поля шага `click` — steps + codegen

**Files:**
- Modify: `farm/recorder/steps.py`
- Modify: `farm/recorder/codegen.py:47-56` (ветка click в `_call`)
- Modify: `tests/test_recorder_steps.py:9-15` и `:39` — **существующие тесты сломаются, их надо обновить**
- Test: `tests/test_recorder_steps.py`, `tests/test_recorder_codegen.py` (дописать)

**Interfaces:**
- Consumes: формат шага из steps.py (`kind/args/selector/param/note`).
- Produces: нормализованный шаг получает ключи `texts: list[str]`, `crop: str | None`, `point: list[float] | None`; codegen рендерит `ctx.click_target(...)`, когда задано любое из них. Task 12 сохраняет ассеты для `crop`.

- [ ] **Step 1: Обновить два существующих теста**

`normalize_step` начнёт возвращать больше ключей — два теста, сверяющие набор ключей точно, сломаются. Обновить заранее, иначе не отличить свою поломку от ожидаемой.

`tests/test_recorder_steps.py`, строки 9–15 — добавить новые ключи в ожидаемый словарь:

```python
    assert result == {
        "kind": "tap",
        "args": {"x": 0.5, "y": 1.0},
        "selector": None,
        "param": None,
        "note": "",
        "texts": [],
        "crop": None,
        "point": None,
        "any": None,
    }
```

`tests/test_recorder_steps.py`, строка 39:

```python
    assert set(result) == {"kind", "args", "selector", "param", "note",
                           "texts", "crop", "point", "any"}
```

Ключ `any` добавляется в Task 14, но объявляется здесь: `normalize_step`
возвращает один и тот же набор ключей для всех шагов, и переписывать эти же
два теста дважды незачем. Значит, Task 11 сразу заводит `"any": None` в
возвращаемом словаре, а разбор признаков появится в Task 14.

- [ ] **Step 2: Падающие тесты**

Дописать в `tests/test_recorder_steps.py`:

```python
def test_запасные_слои_click_нормализуются():
    result = steps.normalize_step({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Войти"'},
        "texts": [" Войти ", "Log in", "Войти"],
        "crop": "07_login.png",
        "point": [0.52, 0.81],
    })
    assert result["texts"] == ["Войти", "Log in"]   # обрезка пробелов и дедуп
    assert result["crop"] == "07_login.png"
    assert result["point"] == [0.52, 0.81]


def test_click_без_слоёв_даёт_пустые_значения():
    result = steps.normalize_step({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Ок"'},
    })
    assert result["texts"] == []
    assert result["crop"] is None
    assert result["point"] is None


def test_кроп_с_выходом_из_папки_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click",
            "selector": {"call": "click", "args": 'text="Ок"'},
            "crop": "../побег.png",
        })


def test_координаты_вне_диапазона_отвергаются():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click",
            "selector": {"call": "click", "args": 'text="Ок"'},
            "point": [1.5, 0.5],
        })


def test_слои_запрещены_другим_шагам():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "sleep", "args": {"seconds": 1},
                              "texts": ["x"]})
```

Дописать в `tests/test_recorder_codegen.py` (используя местные помощники `build` и `body`):

```python
def test_click_со_слоями_рендерит_click_target():
    text = codegen.render(META, {}, build({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Войти"',
                     "fallbacks": ['description="Войти"']},
        "texts": ["Войти", "Log in"],
        "crop": "07_login.png",
        "point": [0.52, 0.81],
    }), DAY)
    assert body(text) == [
        'ctx.click_target(sel=[dict(text="Войти"), dict(description="Войти")], '
        'text=["Войти", "Log in"], img="07_login.png", at=(0.52, 0.81))'
    ]


def test_click_без_слоёв_рендерится_как_прежде():
    text = codegen.render(META, {}, build({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Ок"'},
    }), DAY)
    assert body(text) == ['ctx.click(text="Ок")']
```

Run: `.venv/bin/python -m pytest tests/test_recorder_steps.py tests/test_recorder_codegen.py -v` → новые FAIL.

- [ ] **Step 3: `steps.py`**

После `MAX_FALLBACKS = 3`:

```python
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
```

`normalize_step` — расширенный возврат (`"any"` пока заглушка, разбор в Task 14):

```python
    return {
        "kind": kind,
        "args": _args(kind, raw.get("args")),
        "selector": _selector(kind, raw.get("selector")),
        "param": _param(kind, raw.get("param")),
        "note": _text(raw.get("note")),
        "texts": _texts(kind, raw.get("texts")),
        "crop": _crop(kind, raw.get("crop")),
        "point": _point(kind, raw.get("point")),
        "any": None,
    }
```

- [ ] **Step 4: `codegen.py`**

Ветку `click` в `_call` (строки 50–56) заменить целиком:

```python
    if kind == "click":
        selector = step["selector"]
        chain = [selector["args"], *(selector.get("fallbacks") or [])]
        texts = step.get("texts") or []
        crop = step.get("crop")
        point = step.get("point")
        if texts or crop or point:
            parts = ["sel=[" + ", ".join(f"dict({a})" for a in chain) + "]"]
            if texts:
                parts.append("text=[" + ", ".join(literal(t) for t in texts) + "]")
            if crop:
                parts.append(f"img={literal(crop)}")
            if point:
                parts.append(f"at=({_num(point[0])}, {_num(point[1])})")
            return "ctx.click_target(" + ", ".join(parts) + ")"
        if len(chain) > 1:
            return "ctx.click_any(" + ", ".join(f"dict({a})" for a in chain) + ")"
        return f"ctx.click({chain[0]})"
```

- [ ] **Step 5: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 201 passed, 4 skipped.

---

### Task 12: Ассеты при сохранении и удалении сценария

**Files:**
- Modify: `farm/recorder/save.py`
- Modify: `farm/api/recorder.py:36-46` (эндпоинт save)
- Modify: `farm/api/scenarios.py:44-52` (эндпоинт delete)
- Test: `tests/test_recorder_save.py` (дописать)

**Interfaces:**
- Consumes: `save.target_path`, формат шага из Task 11.
- Produces: `save.save(key, meta, params, steps, overwrite=False, assets=None, screen_width=None) -> Path`, где `assets: dict[имя, base64-png]`; `save.assets_dir(key) -> Path`; `save.delete_assets(key) -> None`. API save принимает `assets` и `screen_width` в теле запроса; API delete чистит папку ассетов.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_recorder_save.py` (фикстура файла называется `scen_dir`; наверх добавить `import base64`, `import json`):

```python
КРОП = base64.b64encode("png-байты".encode("utf-8")  # bytes-литерал кириллицу не принимает).decode()

ШАГ_С_КРОПОМ = [steps.normalize_step({
    "kind": "click",
    "selector": {"call": "click", "args": 'text="Ок"'},
    "crop": "01_ok.png",
})]


def test_ассеты_сохраняются_рядом_со_сценарием(scen_dir):
    save.save("demo", META, {}, ШАГ_С_КРОПОМ,
              assets={"01_ok.png": КРОП}, screen_width=1080)
    assets = scen_dir / "demo_assets"
    assert (assets / "01_ok.png").read_bytes() == "png-байты".encode("utf-8")  # bytes-литерал кириллицу не принимает
    assert json.loads((assets / "meta.json").read_text("utf-8")) == {"screen_width": 1080}


def test_имя_ассета_с_выходом_из_папки_отвергается(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets={"../побег.png": КРОП})


def test_ассет_не_base64_отвергается(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets={"01_ok.png": "не base64!!!"})


def test_битый_ассет_не_оставляет_файл_сценария(scen_dir):
    with pytest.raises(save.SaveError):
        save.save("demo", META, {}, ШАГ_С_КРОПОМ, assets={"01_ok.png": "не base64!!!"})
    assert not (scen_dir / "demo.py").exists()


def test_удаление_ассетов_сносит_папку(scen_dir):
    save.save("demo", META, {}, ШАГ_С_КРОПОМ,
              assets={"01_ok.png": КРОП}, screen_width=720)
    save.delete_assets("demo")
    assert not (scen_dir / "demo_assets").exists()


def test_удаление_ассетов_у_негодного_ключа_молчит(scen_dir):
    save.delete_assets("../беда")   # не бросает: удаление не должно падать
```

Run: `.venv/bin/python -m pytest tests/test_recorder_save.py -v` → новые FAIL.

- [ ] **Step 2: `save.py`**

Импорты: добавить `import base64`, `import binascii`, `import json`, `import shutil`.

```python
ASSET_RE = re.compile(r"^[a-z0-9_][a-z0-9_.-]{0,60}\.png$")
MAX_ASSETS = 60
MAX_ASSET_BYTES = 300_000  # кроп кнопки; полноэкранный снимок сюда не влезет — и не должен


def assets_dir(key) -> Path:
    """Папка ассетов сценария; ключ проверяется так же, как в target_path."""
    path = target_path(key)
    return path.with_name(f"{path.stem}_assets")


def delete_assets(key) -> None:
    """Снести папку ассетов. Негодный ключ и отсутствие папки — не ошибка:
    удаление вызывается из эндпоинта, который уже отработал по .py-файлу."""
    try:
        shutil.rmtree(assets_dir(key), ignore_errors=True)
    except SaveError:
        pass


def _write_assets(key, assets: dict, screen_width) -> None:
    if len(assets) > MAX_ASSETS:
        raise SaveError(f"слишком много ассетов: {len(assets)} > {MAX_ASSETS}")
    decoded = {}
    for name, b64 in assets.items():
        if not isinstance(name, str) or not ASSET_RE.match(name):
            raise SaveError(f"имя ассета «{name}»: png из латиницы, цифр, _ . -")
        try:
            data = base64.b64decode(b64, validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise SaveError(f"ассет «{name}»: не base64")
        if len(data) > MAX_ASSET_BYTES:
            raise SaveError(f"ассет «{name}» больше {MAX_ASSET_BYTES} байт")
        decoded[name] = data
    directory = assets_dir(key)
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in decoded.items():
        (directory / name).write_bytes(data)
    if screen_width:
        (directory / "meta.json").write_text(
            json.dumps({"screen_width": int(screen_width)}), "utf-8")
```

Новая сигнатура `save`:

```python
def save(key, meta: dict, params: dict, steps: list, overwrite: bool = False,
         assets: dict | None = None, screen_width: int | None = None) -> Path:
    if not steps:
        raise SaveError("нет ни одного шага")
    path = target_path(key)
    if path.exists() and not overwrite:
        raise Conflict(f"сценарий «{key}» уже существует")
    if assets:
        # ассеты пишутся до .py: битый ассет не оставит сценарий-сироту,
        # ссылающийся на несуществующие кропы
        _write_assets(key, assets, screen_width)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(codegen.render(meta, params, steps), "utf-8")
    return path
```

- [ ] **Step 3: API**

`farm/api/recorder.py`, эндпоинт `save_scenario` — вызов:

```python
        path = saver.save(payload.get("key"), meta, params, items,
                          bool(payload.get("overwrite")),
                          assets=payload.get("assets"),
                          screen_width=payload.get("screen_width"))
```

`farm/api/scenarios.py`, `delete_scenario` — после `Path(scenario.path).unlink(missing_ok=True)`:

```python
    saver.delete_assets(key)
```

Импорт `from ..recorder import save as saver` поднять к остальным импортам модуля (посмотри их порядок на месте).

- [ ] **Step 4: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 207 passed, 4 skipped.

---

## Этап 3 — якоря

### Task 13: `ctx.expect_screen`

**Files:**
- Modify: `farm/context.py` (импорт `tree`, новые методы)
- Test: `tests/test_context_resilience.py` (дописать)

**Interfaces:**
- Consumes: `ctx.exists`, `ctx._rescue` (Task 5), `ctx.asset` и `ctx.screenshot` (Task 10), `farm.ui.tree.parse`, `ctx.current_app`.
- Produces: `ctx.expect_screen(name: str, any: list[dict] | None = None, timeout: float = 10) -> None`. Task 14 генерит вызовы.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_context_resilience.py`:

```python
def test_якорь_проходит_по_признаку(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "exists",
                        lambda timeout=0.5, **sel: sel == {"text": "Вход"})
    ctx.expect_screen("login", any=[dict(resourceId="нет"), dict(text="Вход")],
                      timeout=0.5)   # не бросил исключение — значит, прошло


def test_якорь_спасается_стражем(monkeypatch):
    ctx = ctx_()
    state = {"rescued": False}
    monkeypatch.setattr(ctx, "exists", lambda timeout=0.5, **sel: state["rescued"])
    ctx._guards = СпасающиеСтражи(state)
    ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0.1)


def test_якорь_падает_с_описанием_чужого_экрана(monkeypatch):
    ctx = ctx_()
    monkeypatch.setattr(ctx, "exists", lambda timeout=0.5, **sel: False)
    monkeypatch.setattr(ctx, "current_app", lambda: "com.app.main")
    monkeypatch.setattr(ctx, "_screen_texts", lambda limit=5: ["Продолжить", "Пропустить"])
    monkeypatch.setattr(ctx, "_expect_artifacts", lambda name: None)
    ctx._guards = МолчащиеСтражи()
    with pytest.raises(StepFailed) as err:
        ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0.1)
    message = str(err.value)
    assert "login" in message
    assert "com.app.main" in message
    assert "Продолжить" in message


def test_якорь_без_признаков_отвергается():
    with pytest.raises(ValueError):
        ctx_().expect_screen("login", any=[])
```

Run: `.venv/bin/python -m pytest tests/test_context_resilience.py -v` → новые FAIL.

- [ ] **Step 2: Имплементация**

`farm/context.py` — импорт: `from .ui import tree`. Новые методы после `click_target`:

```python
    def expect_screen(self, name: str, any: list | None = None,
                      timeout: float = 10) -> None:
        """Якорь: убедиться, что мы на экране «name», прежде чем действовать.

        Чужой экран ловится здесь — до клика, а не через три шага тапов
        в пустоту.
        """
        features = list(any or [])
        if not features:
            raise ValueError(f"expect_screen({name!r}) без признаков экрана")
        self.check_cancel()
        if self._wait_features(features, timeout):
            return
        if self._rescue() and self._wait_features(features, 5):
            return
        try:
            app = self.current_app()
        except Exception:  # noqa: BLE001
            app = "?"
        texts = ", ".join(self._screen_texts())
        self._expect_artifacts(name)
        self.fail(f"ожидал экран «{name}», вижу {app}: [{texts}]")

    def _wait_features(self, features: list, timeout: float) -> bool:
        end = time.time() + timeout
        while True:
            for feature in features:
                self.check_cancel()
                if self.exists(timeout=0.5, **feature):
                    return True
            if time.time() >= end:
                return False

    def _screen_texts(self, limit: int = 5) -> list:
        """Верхние тексты экрана — чтобы сообщение об ошибке было читаемым."""
        try:
            w, h = self.size
            nodes = tree.parse(self.dump_hierarchy(), w, h)
        except Exception:  # noqa: BLE001
            return []
        out = []
        for node in nodes:
            label = (node.text or node.description or "").strip()
            if label and label not in out:
                out.append(label)
            if len(out) >= limit:
                break
        return out

    def _expect_artifacts(self, name: str) -> None:
        """Пара expected/actual в артефакты — расхождение видно глазами."""
        try:
            self.screenshot(f"actual_{name}")
        except Exception:  # noqa: BLE001
            pass
        data, _ = self.asset(f"expect_{name}.png")
        if data and self.artifacts_dir:
            try:
                (Path(self.artifacts_dir) / f"expected_{name}.png").write_bytes(data)
                self.log(f"эталон экрана «{name}» приложен к артефактам")
            except OSError:
                pass
```

- [ ] **Step 3: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 211 passed, 4 skipped.

---

### Task 14: Шаг `expect` в конструкторе — steps + codegen

**Files:**
- Modify: `farm/recorder/steps.py`
- Modify: `farm/recorder/codegen.py` (`_call`)
- Test: `tests/test_recorder_steps.py`, `tests/test_recorder_codegen.py` (дописать)

**Interfaces:**
- Consumes: нормализация из Task 11, `ctx.expect_screen` из Task 13.
- Produces: kind `expect` с `args.name: str` и полем `any: list[str]` — строки аргументов u2-селекторов, тот же формат, что `selector.args` и `fallbacks` у click. Codegen рендерит `ctx.expect_screen("login", any=[dict(...)])`.

- [ ] **Step 1: Падающие тесты**

Дописать в `tests/test_recorder_steps.py`:

```python
def test_шаг_expect_нормализуется():
    result = steps.normalize_step({
        "kind": "expect",
        "args": {"name": "login"},
        "any": ['resourceId="com.app:id/title"', 'text="Вход"'],
    })
    assert result["kind"] == "expect"
    assert result["any"] == ['resourceId="com.app:id/title"', 'text="Вход"']


def test_expect_требует_признаки():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "expect", "args": {"name": "login"},
                              "any": []})


def test_поле_any_запрещено_шагу_click():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click",
            "selector": {"call": "click", "args": 'text="Ок"'},
            "any": ['text="Вход"'],
        })
```

Дописать в `tests/test_recorder_codegen.py`:

```python
def test_expect_рендерит_expect_screen():
    text = codegen.render(META, {}, build({
        "kind": "expect",
        "args": {"name": "login"},
        "any": ['resourceId="com.app:id/title"', 'text="Вход"'],
    }), DAY)
    assert body(text) == [
        'ctx.expect_screen("login", '
        'any=[dict(resourceId="com.app:id/title"), dict(text="Вход")])'
    ]
```

Run: оба файла → FAIL (`неизвестный шаг: 'expect'`).

- [ ] **Step 2: `steps.py`**

В словарь `ARGS` добавить: `"expect": (("name",), ()),`.

Новая функция рядом с `_crop` / `_point`:

```python
ANY_MAX = 3


def _anchor(kind: str, raw):
    """Признаки экрана у шага expect: строки аргументов u2-селекторов."""
    if raw in (None, []):
        if kind == "expect":
            raise StepError("шагу expect нужен хотя бы один признак экрана")
        return None
    if kind != "expect":
        raise StepError(f"поле any допустимо только у expect, не у {kind}")
    if (not isinstance(raw, list)
            or not all(isinstance(s, str) and s.strip() for s in raw)):
        raise StepError("any — непустой список строк-селекторов")
    seen, out = set(), []
    for item in raw:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:ANY_MAX]
```

В `normalize_step` заменить заглушку из Task 11 на реальный разбор:

```python
        "any": _anchor(kind, raw.get("any")),
```

`expect` не входит в `PARAMETRIZABLE` — имя экрана не параметризуется, менять ничего не надо.

- [ ] **Step 3: `codegen.py`**

В `_call`, сразу после ветки `click`:

```python
    if kind == "expect":
        chain = ", ".join(f"dict({a})" for a in step["any"])
        return f'ctx.expect_screen({literal(args["name"])}, any=[{chain}])'
```

- [ ] **Step 4: Зелёные + полный набор**

Run: `.venv/bin/python -m pytest tests/ -q` → 215 passed, 4 skipped.

---

### Task 15: Зависимости и документация

**Files:**
- Create: `requirements-vision.txt`
- Modify: `README.md` (раздел «Свои сценарии», таблица переменных, «Структура»)
- Modify: `scenarios/_template.py`

**Interfaces:** нет — документация.

- [ ] **Step 1: `requirements-vision.txt`**

```text
# Слои зрения резолвера: OCR и поиск по шаблону. Без них ферма работает,
# просто эти два слоя выключены.
opencv-python-headless>=4.9
numpy>=1.26
ocrmac>=1.0 ; sys_platform == "darwin"
pytesseract>=0.3.10 ; sys_platform != "darwin"
```

- [ ] **Step 2: README**

В раздел «Свои сценарии» — подраздел «Устойчивость» с тремя кусками:

```python
# многослойная цель: любой аргумент можно опустить, слои пробуются по порядку
ctx.click_target(sel=[dict(resourceId="com.app:id/login")],
                 text=["Войти", "Log in"], at=(0.5, 0.8))

# якорь: упасть сразу с «ожидал экран X, вижу Y», а не тапать в пустоту
ctx.expect_screen("login", any=[dict(text="Вход")])
```

Плюс абзац про стражей: файлы `guards/global.json` и `guards/<пакет>.json`,
формат из Task 4, `max_fires` как защита от зацикливания, горячая
перезагрузка. И строка про установку зрения:
`pip install -r requirements-vision.txt` (без него OCR и шаблоны выключены).

В таблицу переменных окружения добавить строки: `FARM_SETTLE` (1),
`FARM_SETTLE_TIMEOUT` (3), `FARM_SETTLE_QUIET` (0.4), `FARM_GUARDS_DIR` (guards).

В раздел «Структура» добавить: `guards.py`, `resolve.py`, `vision/`,
`control/stability.py`, папку `guards/`. Заодно поправь устаревшее: там
`runner.py` значится в корне `farm/`, а он живёт в `farm/devices/runner.py`.

- [ ] **Step 3: `scenarios/_template.py`**

Добавить образцы в стиле существующих примеров файла:

```python
    # Многослойная цель: селекторы → текст → OCR → шаблон → координаты.
    # ctx.click_target(sel=[dict(resourceId="com.app:id/login")],
    #                  text=["Войти", "Log in"], at=(0.5, 0.8))

    # Якорь экрана: падение с «ожидал X, вижу Y» вместо тапов в пустоту.
    # ctx.expect_screen("login", any=[dict(text="Вход")])

    # Стражи закрывают известные попапы сами — см. guards/global.json.
```

- [ ] **Step 4: Финальная проверка**

Run: `.venv/bin/python -m pytest tests/ -q` → 215 passed, 4 skipped.
Run: `.venv/bin/python -c "import farm.server"` → импортируется без ошибок.

---

## Self-review плана (выполнен)

**Покрытие спеки:** слой 1 → Task 1–2; слой 2 → Task 3–5; слой 3 → Task 6–12; слой 4 → Task 13–14; зависимости и деградация → Task 7, 8, 15; тесты — в каждой задаче.

**Сверено с кодом перед написанием:** сигнатура `tree.parse(xml, width, height)` и поля `Node`; фикстура `scen_dir` и русские имена тестов в `tests/`; помощники `build`/`body` в `test_recorder_codegen.py`; отсутствие vision-зависимостей в `.venv`; базовая линия 156 тестов.

**Ловушки, заложенные в план явно:** два существующих теста (`test_recorder_steps.py:9-15` и `:39`) сверяют набор ключей `normalize_step` точно и сломались бы — Task 11 Step 1 обновляет их до правки кода; ключ `any` заводится сразу в Task 11, чтобы не переписывать те же тесты дважды в Task 14.

**Осознанные отступления от спеки:**
1. `click_any` не переезжает на резолвер — резолвер держит свой круг по цепочке, а рабочий `click_any` не трогаем (только дополняем спасением стражами).
2. Итоговая сводка телеметрии за прогон («N шагов спасены запасными слоями») и фронтенд рекордера — в следующий план, вместе с правками `static/js/recorder.js`. Пошаговая телеметрия (лог слоя и срабатываний стражей) есть уже здесь.

**Согласованность типов проверена:** `Hit(x, y, layer, detail)`, `asset() -> (bytes | None, float)`, `wait_stable(...) -> bool`, `GuardEngine.try_all(ctx) -> list[str]`, сигнатура `save.save`, набор ключей шага — совпадают между задачами.
