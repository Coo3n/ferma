# Экран сценариев и рекордер: причесать интерфейс — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать карточку сценария информативной (структура + здоровье) и
превратить экран записи из ряда из девяти непонятных кнопок в рабочий стол
«устройство + живая схема», убрав дублирующий свободный канвас.

**Architecture:** Бэкенд получает три маленьких, переиспользующих уже
существующий код добавления (счётчик прогонов на `Runner`, вынесенное
сканирование слепков преград в `detours.py`, обогащение `GET /api/scenarios`).
Фронтенд — чистая перестройка существующей разметки/JS `static/index.html`,
`static/js/{scenarios,recorder}.js`, `static/css/{work,recorder}.css`, без
новых зависимостей. Свободный drag-канвас (`static/js/canvas.js`,
`static/css/canvas.css`) удаляется целиком — его функцию берёт на себя уже
работающая «схема» (`schSpine`/`schSide` из `recorder.js`), просто
превращённая из модалки в постоянную панель.

**Tech Stack:** Python 3 / FastAPI (бэкенд, `pytest` для тестов), ванильный
JS без сборки (фронтенд, ручная проверка в браузере — в проекте нет JS-тестов
и `package.json`).

## Global Constraints

- Палитра, типографика, отступы — только существующие токены `base.css`
  (`--ok`/`--warn`/`--bad`/`--dim`/`--accent`/`--mono`, класс `.tnum`,
  `.chip`/`.chip.on`, `.box h3` для подписей групп). Новых токенов не вводим.
- Свободный холст со стрелками произвольной формы не делаем — граф сюжета
  остаётся хребтом вниз + ветками вправо (`schSpine`/`schArms`), это уже
  принятое и работающее решение из `docs/superpowers/specs/2026-09-12-branching-scenarios-design.md`.
  Не пересматривать.
- Кнопка «Запустить сценарий» остаётся на панели фермы (`fleet.js` /
  `runbar`), на экран сценариев не переезжает.
- Тесты — только бэкенд (`pytest`, стиль прямого вызова функций роута без
  `TestClient`, см. `tests/test_detour_api.py`). Фронтенд проверяется вручную
  через запущенный `run.sh` — автотестов для JS в проекте нет и мы их не
  заводим.
- Никаких `git commit` — репозиторий не инициализирован под git в этой
  рабочей копии (`git status` даёт `fatal: not a git repository`).

---

## Обзор изменяемых файлов

| Файл | Что меняется |
|---|---|
| `farm/api/detours.py` | Сканирование слепков выносится в `scan_obstacles()` — переиспользуется вторым местом |
| `farm/devices/runner.py` | Новый метод `Runner.scenario_stats(key)` |
| `farm/api/scenarios.py` | `GET /api/scenarios` отдаёт `steps`/`branches`/`passed`/`failed`/`uncovered` |
| `tests/test_detour_api.py` | Тесты на `scan_obstacles()` |
| `tests/test_scenarios_api.py` | **Новый.** Тесты на обогащённый `list_scenarios()` |
| `static/js/scenarios.js` | Вторая строка карточки: структура + здоровье |
| `static/css/work.css` | Стили второй строки карточки |
| `static/index.html` | Группировка кнопок панели записи; снос `#cv`; новый `#recScheme` рядом с `#recSteps` |
| `static/css/recorder.css` | `.sch` — один столбец вместо двух (панель уже, не модалка) |
| `static/js/recorder.js` | `REC.view`, `recSetView()`, живая схема вместо модалки, снятие ссылок на канвас |
| `static/js/canvas.js` | **Удаляется** |
| `static/css/canvas.css` | **Удаляется** |

---

## Task 1: Бэкенд — структура и здоровье сценария

**Files:**
- Modify: `farm/api/detours.py:94-136` (вынести сканирование в функцию)
- Modify: `farm/devices/runner.py` (добавить метод после `list_jobs`, строка ~391)
- Modify: `farm/api/scenarios.py` (обогатить `list_scenarios`)
- Test: `tests/test_detour_api.py` (дописать тесты на `scan_obstacles`)
- Test: `tests/test_scenarios_api.py` (новый файл)

**Interfaces:**
- Produces: `scan_obstacles(package: str = "") -> list[dict]` в
  `farm/api/detours.py` — список слепков преград (те же словари, что раньше
  собирались инлайном в `detour_map`).
- Produces: `Runner.scenario_stats(self, key: str, limit: int = 50) -> dict`
  — `{"passed": int, "failed": int}` по последним завершённым прогонам
  сценария.
- Produces: `GET /api/scenarios` — каждый элемент списка получает поля
  `steps: int | None`, `branches: int | None`, `passed: int`, `failed: int`,
  `uncovered: int | None`.

### Шаг 1.1: Вынести сканирование слепков в `scan_obstacles()`

- [ ] **Написать падающий тест**

Добавить в конец `tests/test_detour_api.py`:

```python
def test_scan_obstacles_читает_слепки_из_артефактов(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(
        json.dumps({"package": "com.app", "texts": ["Тариф"],
                    "candidates": [{"selector": {"text": "Тариф"}}]}),
        "utf-8")

    слепки = scan_obstacles("com.app")
    assert len(слепки) == 1
    assert слепки[0]["job"] == "job1"
    assert слепки[0]["file"] == "obstacle.json"


def test_scan_obstacles_фильтрует_по_пакету(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(
        json.dumps({"package": "com.other", "texts": [], "candidates": []}),
        "utf-8")

    assert scan_obstacles("com.app") == []


def test_scan_obstacles_без_пакета_не_фильтрует(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(
        json.dumps({"package": "com.other", "texts": [], "candidates": []}),
        "utf-8")

    assert len(scan_obstacles("")) == 1


def test_scan_obstacles_без_папки_артефактов_не_падает(tmp_path, monkeypatch):
    from farm import config
    from farm.api.detours import scan_obstacles

    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "нет-такой-папки")
    assert scan_obstacles("com.app") == []
```

- [ ] **Убедиться, что тест падает**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/pytest tests/test_detour_api.py -k scan_obstacles -v`
Expected: FAIL — `ImportError: cannot import name 'scan_obstacles'`

- [ ] **Вынести функцию**

В `farm/api/detours.py` заменить тело `detour_map` (строки 94-136):

Было:
```python
@router.get("")
def detour_map(package: str = ""):
    """Карта отводов: что уже умеем обходить и обо что ещё спотыкаемся.

    Непокрытые преграды собираются из артефактов упавших задач. Они и есть
    смысл этой карты: ферма встречала их в бою, но обходить не научена.
    """
    rules = [
        # when отдаём в том же виде, в каком он лежит в файле стражей:
        # Guard.when — это уже развёрнутый список, и разные формы одного поля
        # в API и на диске путали бы и фронт, и расчёт непокрытых преград.
        {"name": g.name, "when": {"any": g.when},
         "action": g.action, "source": g.source}
        for g in guards.load(package)
    ]

    слепки = []
    корень = Path(config.ARTIFACTS_DIR)
    if корень.is_dir():
        # свежие задачи первыми: старые падения чинить уже поздно
        папки = sorted(корень.iterdir(), key=lambda p: p.stat().st_mtime
                       if p.exists() else 0, reverse=True)
        for папка in папки[:MAP_SCAN_JOBS]:
            if not папка.is_dir():
                continue
            # Слепков в задаче несколько: obstacle.json от падения и
            # obstacle_escaped_NN.json на каждый экран, обойдённый вслепую.
            # Вторые не менее ценны: прогон доехал, но чем был тот экран,
            # ферма не знает, и вслепую обходит его каждый раз заново.
            for файл in sorted(папка.glob("obstacle*.json")):
                try:
                    слепок = json.loads(файл.read_text("utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(слепок, dict):
                    continue
                if package and слепок.get("package") != package:
                    continue
                слепок["job"] = папка.name
                слепок["file"] = файл.name
                слепки.append(слепок)

    return {"rules": rules, "obstacles": obstacle.uncovered(слепки, rules)}
```

Стало:
```python
def scan_obstacles(package: str = "") -> list:
    """Слепки преград из артефактов последних задач, свежие первыми.

    Слепков в задаче несколько: obstacle.json от падения и
    obstacle_escaped_NN.json на каждый экран, обойдённый вслепую. Вторые не
    менее ценны: прогон доехал, но чем был тот экран, ферма не знает, и
    вслепую обходит его каждый раз заново.

    Вынесено из detour_map(): список сценариев тоже считает непокрытые
    преграды по пакету (для бейджа здоровья), и второй копии этого сканирования
    заводить незачем.
    """
    слепки = []
    корень = Path(config.ARTIFACTS_DIR)
    if not корень.is_dir():
        return слепки
    # свежие задачи первыми: старые падения чинить уже поздно
    папки = sorted(корень.iterdir(), key=lambda p: p.stat().st_mtime
                   if p.exists() else 0, reverse=True)
    for папка in папки[:MAP_SCAN_JOBS]:
        if not папка.is_dir():
            continue
        for файл in sorted(папка.glob("obstacle*.json")):
            try:
                слепок = json.loads(файл.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(слепок, dict):
                continue
            if package and слепок.get("package") != package:
                continue
            слепок["job"] = папка.name
            слепок["file"] = файл.name
            слепки.append(слепок)
    return слепки


@router.get("")
def detour_map(package: str = ""):
    """Карта отводов: что уже умеем обходить и обо что ещё спотыкаемся.

    Непокрытые преграды собираются из артефактов упавших задач. Они и есть
    смысл этой карты: ферма встречала их в бою, но обходить не научена.
    """
    rules = [
        # when отдаём в том же виде, в каком он лежит в файле стражей:
        # Guard.when — это уже развёрнутый список, и разные формы одного поля
        # в API и на диске путали бы и фронт, и расчёт непокрытых преград.
        {"name": g.name, "when": {"any": g.when},
         "action": g.action, "source": g.source}
        for g in guards.load(package)
    ]
    return {"rules": rules, "obstacles": obstacle.uncovered(scan_obstacles(package), rules)}
```

- [ ] **Прогнать тесты**

Run: `.venv/bin/pytest tests/test_detour_api.py -v`
Expected: все тесты PASS, включая новые `test_scan_obstacles_*` и старые
`test_отвод_создаёт_блок_и_стража` и т.д. (регрессий нет — `detour_map`
снаружи ведёт себя так же).

### Шаг 1.2: `Runner.scenario_stats()`

- [ ] **Написать падающий тест**

Создать `tests/test_runner_stats.py`:

```python
"""Итог прогонов сценария: сколько прошло, сколько упало."""
from farm.devices.runner import FAILED, PASSED, QUEUED, Job, Runner


def _job(scenario_key: str, status: str) -> Job:
    return Job(id=f"{scenario_key}-{status}-{id(object())}",
               scenario_key=scenario_key, scenario_name=scenario_key,
               serial="dev1", device_name="dev1", params={}, status=status)


def test_считает_только_свой_сценарий():
    runner = Runner()
    for j in [_job("a", PASSED), _job("a", FAILED), _job("b", PASSED)]:
        runner.jobs[j.id] = j
        runner.order.append(j.id)

    stats = runner.scenario_stats("a")
    assert stats == {"passed": 1, "failed": 1}


def test_незавершённые_не_считаются():
    runner = Runner()
    for j in [_job("a", PASSED), _job("a", QUEUED)]:
        runner.jobs[j.id] = j
        runner.order.append(j.id)

    assert runner.scenario_stats("a") == {"passed": 1, "failed": 0}


def test_пустая_история_даёт_нули():
    runner = Runner()
    assert runner.scenario_stats("нет-такого") == {"passed": 0, "failed": 0}


def test_limit_режет_старые_попытки():
    runner = Runner()
    # порядок в self.order — от старых к новым; scenario_stats идёт с конца
    for i in range(5):
        j = _job("a", PASSED if i < 3 else FAILED)
        runner.jobs[j.id] = j
        runner.order.append(j.id)

    stats = runner.scenario_stats("a", limit=2)
    assert stats["passed"] + stats["failed"] == 2
    assert stats == {"passed": 0, "failed": 2}   # два последних — FAILED
```

- [ ] **Убедиться, что тест падает**

Run: `.venv/bin/pytest tests/test_runner_stats.py -v`
Expected: FAIL — `AttributeError: 'Runner' object has no attribute 'scenario_stats'`

(Если `Runner()` без аргументов не создаётся — проверить `__init__` и при
необходимости поправить тест под реальную сигнатуру конструктора, она не
трогается этим планом.)

- [ ] **Добавить метод**

В `farm/devices/runner.py` после `list_jobs` (после строки `return out` на
позиции ~391, перед `def get`):

```python
    def scenario_stats(self, key: str, limit: int = 50) -> dict:
        """Итог последних прогонов сценария: сколько прошло, сколько упало.

        Считает только завершённые попытки (passed/failed) — очередь и
        текущий прогон исходу ещё не подведены, добавлять их в знаменатель
        нечестно.
        """
        with self._lock:
            ids = list(self.order)[::-1]
        passed = failed = 0
        seen = 0
        for jid in ids:
            job = self.jobs.get(jid)
            if job is None or job.scenario_key != key or job.status not in (PASSED, FAILED):
                continue
            if job.status == PASSED:
                passed += 1
            else:
                failed += 1
            seen += 1
            if seen >= limit:
                break
        return {"passed": passed, "failed": failed}
```

- [ ] **Прогнать тесты**

Run: `.venv/bin/pytest tests/test_runner_stats.py -v`
Expected: все 4 теста PASS

### Шаг 1.3: Обогатить `GET /api/scenarios`

- [ ] **Написать падающий тест**

Создать `tests/test_scenarios_api.py`:

```python
"""GET /api/scenarios: структура и здоровье в карточке."""
import json

import pytest

from farm import config, guards, scenarios
from farm.api import scenarios as api
from farm.devices.runner import FAILED, PASSED, Job
from farm.devices.runner import runner as глобальный_runner
from farm.recorder import save, steps


@pytest.fixture
def песочница(tmp_path, monkeypatch):
    scen, grd, art = tmp_path / "scenarios", tmp_path / "guards", tmp_path / "artifacts"
    scen.mkdir(), grd.mkdir(), art.mkdir()
    monkeypatch.setattr(config, "SCENARIOS_DIR", scen)
    monkeypatch.setattr(config, "GUARDS_DIR", grd)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", art)
    scenarios._cache.clear()
    guards._cache.clear()
    yield scen, grd, art
    # чужие Job из других тестов, использующих тот же глобальный runner, не
    # трогаем — но свои подчищаем, чтобы не текли между тестами файла
    for jid in list(глобальный_runner.jobs):
        if глобальный_runner.jobs[jid].scenario_key.startswith("test_"):
            глобальный_runner.jobs.pop(jid, None)
            try:
                глобальный_runner.order.remove(jid)
            except ValueError:
                pass


def _recorded(key: str, params: dict) -> None:
    meta = {"name": key, "description": "", "watch_popups": False}
    шаги = [
        steps.normalize_step({"kind": "unlock", "args": {}}),
        steps.normalize_step({
            "kind": "branch",
            "args": {"name": "экран"},
            "arms": [{"name": "ветка", "any": [], "run": ""}],
        }),
    ]
    save.save(key, meta, params, шаги)


def test_голый_py_без_рецепта_не_даёт_структуру(песочница):
    scen, _, _ = песочница
    (scen / "test_руками.py").write_text(
        "NAME = 'Руками'\n\ndef run(ctx):\n    pass\n", "utf-8")

    item = next(i for i in api.list_scenarios() if i["key"] == "test_руками")
    assert item["editable"] is False
    assert item["steps"] is None
    assert item["branches"] is None


def test_записанный_сценарий_даёт_шаги_и_развилки(песочница):
    _recorded("test_demo", {})

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["editable"] is True
    assert item["steps"] == 2
    assert item["branches"] == 1


def test_без_пакета_в_параметрах_преграды_не_считаются(песочница):
    _recorded("test_demo", {})

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["uncovered"] is None


def test_пакет_из_параметра_считает_непокрытые_преграды(песочница):
    scen, grd, art = песочница
    _recorded("test_demo", {"package": {"label": "Пакет", "default": "com.app"}})

    job_dir = art / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(json.dumps({
        "package": "com.app", "texts": ["Тариф"],
        "candidates": [{"selector": {"text": "Тариф"}}],
    }), "utf-8")

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["uncovered"] == 1


def test_отвод_закрывает_преграду(песочница):
    scen, grd, art = песочница
    _recorded("test_demo", {"package": {"label": "Пакет", "default": "com.app"}})

    job_dir = art / "job1"
    job_dir.mkdir()
    (job_dir / "obstacle.json").write_text(json.dumps({
        "package": "com.app", "texts": ["Тариф"],
        "candidates": [{"selector": {"text": "Тариф"}}],
    }), "utf-8")
    (grd / "com.app.json").write_text(json.dumps([
        {"name": "закрыть", "when": [{"text": "Тариф"}], "action": {"run": "test_demo"}},
    ]), "utf-8")
    guards._cache.clear()

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["uncovered"] == 0


def test_прогоны_считаются_по_ключу_сценария(песочница):
    _recorded("test_demo", {})
    for status in (PASSED, PASSED, FAILED):
        j = Job(id=f"test_demo-{status}-{len(глобальный_runner.jobs)}",
                scenario_key="test_demo", scenario_name="test_demo",
                serial="dev1", device_name="dev1", params={}, status=status)
        глобальный_runner.jobs[j.id] = j
        глобальный_runner.order.append(j.id)

    item = next(i for i in api.list_scenarios() if i["key"] == "test_demo")
    assert item["passed"] == 2
    assert item["failed"] == 1
```

- [ ] **Убедиться, что тест падает**

Run: `.venv/bin/pytest tests/test_scenarios_api.py -v`
Expected: FAIL на всех тестах, кроме первого — `KeyError: 'steps'` и т.п.
(поля ещё не существуют).

- [ ] **Обогатить роут**

В `farm/api/scenarios.py` заменить блок импортов и `list_scenarios`:

Было:
```python
from .. import scenarios
from ..devices.runner import runner
from ..recorder import save as saver

router = APIRouter()


@router.get("/api/scenarios")
def list_scenarios(reload: bool = Query(False)):
    out = []
    for s in scenarios.discover(force=reload):
        item = s.to_dict()
        # Правка открывается только по рецепту: .py обратно в шаги не
        # разбирается. У сценариев, записанных до появления рецептов, кнопки
        # правки не будет — врать про неё хуже, чем не показывать.
        item["editable"] = bool(s.recorded and saver.has_recipe(s.key))
        out.append(item)
    return out
```

Стало:
```python
from .. import guards, obstacle, scenarios
from ..devices.runner import runner
from ..recorder import save as saver
from .detours import scan_obstacles

router = APIRouter()


def _structure(key: str) -> tuple[int | None, int | None]:
    """Число шагов и развилок в рецепте — только у сценариев из конструктора."""
    рецепт = saver.load_recipe(key)
    if not рецепт:
        return None, None
    шаги = рецепт.get("steps") or []
    ветки = sum(1 for шаг in шаги if шаг.get("kind") == "branch")
    return len(шаги), ветки


def _package_of(params: dict) -> str:
    """Пакет из параметра `package`, если сценарий его объявляет.

    Параметр хранится либо как голое значение, либо как словарь со `default`
    — тем же способом, что разбирает paramField() на фронте.
    """
    raw = (params or {}).get("package")
    if isinstance(raw, dict):
        return str(raw.get("default") or "")
    return str(raw or "")


def _uncovered(package: str) -> int | None:
    """Непокрытые преграды по пакету приложения — не по сценарию: пакет мог
    получить преграду через любой из бьющих в него сценариев."""
    if not package:
        return None
    rules = [{"when": {"any": g.when}} for g in guards.load(package)]
    return len(obstacle.uncovered(scan_obstacles(package), rules))


@router.get("/api/scenarios")
def list_scenarios(reload: bool = Query(False)):
    out = []
    for s in scenarios.discover(force=reload):
        item = s.to_dict()
        # Правка открывается только по рецепту: .py обратно в шаги не
        # разбирается. У сценариев, записанных до появления рецептов, кнопки
        # правки не будет — врать про неё хуже, чем не показывать.
        item["editable"] = bool(s.recorded and saver.has_recipe(s.key))
        item["steps"], item["branches"] = (
            _structure(s.key) if item["editable"] else (None, None))
        stats = runner.scenario_stats(s.key)
        item["passed"], item["failed"] = stats["passed"], stats["failed"]
        item["uncovered"] = _uncovered(_package_of(s.params))
        out.append(item)
    return out
```

- [ ] **Прогнать тесты**

Run: `.venv/bin/pytest tests/test_scenarios_api.py -v`
Expected: все 6 тестов PASS

- [ ] **Прогнать весь набор — проверить, что ничего не сломалось**

Run: `.venv/bin/pytest -q`
Expected: все тесты PASS (было 281 в прошлом спеке + новые из этого плана)

---

## Task 2: Экран сценариев — вторая строка карточки

**Files:**
- Modify: `static/js/scenarios.js:25-50` (`scenarioCard`)
- Modify: `static/css/work.css` (после блока `.sc .er`, строка 31)

**Interfaces:**
- Consumes: поля `steps`, `branches`, `passed`, `failed`, `uncovered` из
  `GET /api/scenarios` (Task 1).

### Шаг 2.1: Отрисовать вторую строку

- [ ] **Изменить `scenarioCard`**

В `static/js/scenarios.js` заменить функцию (строки 25-50):

Было:
```javascript
function scenarioCard(scenario) {
    const lastErrorLine = String(scenario.error || '').split('\n').filter(Boolean).pop();
    const mark = scenario.recorded
        ? '<svg class="ic rec-mark"><title>Записано конструктором</title><use href="#i-record"/></svg>'
        : '';
    const drop = scenario.recorded
        ? `<button class="sm danger" title="Удалить сценарий"
             aria-label="Удалить сценарий ${esc(scenario.name)}"
             onclick="event.stopPropagation();deleteScenario('${scenario.key}')">
             <svg class="ic"><use href="#i-trash"/></svg></button>`
        : '';
    /* Правка только у сценариев с рецептом: .py обратно в шаги не
       разбирается (см. GET /api/recorder/recipe). */
    const edit = scenario.editable
        ? `<button class="sm" title="Править шаги в конструкторе"
             aria-label="Править сценарий ${esc(scenario.name)}"
             onclick="event.stopPropagation();editScenario('${scenario.key}')">
             <svg class="ic"><use href="#i-pencil"/></svg></button>`
        : '';
    return `<div class="sc ${S.scenario === scenario.key ? 'on' : ''}"
               onclick="pickScenario('${scenario.key}')">
    <div class="nm">${mark}<span>${esc(scenario.name)}</span>${edit}${drop}</div>
    ${scenario.description ? `<div class="ds">${esc(scenario.description)}</div>` : ''}
    ${scenario.error ? `<div class="er">${esc(lastErrorLine)}</div>` : ''}
  </div>`;
}
```

Стало (добавлены `scenarioStructure` и `scenarioHealth`, вставлены в разметку):
```javascript
/* Вторая строка карточки: сколько в сценарии шагов и развилок. Только у
   записанных конструктором — сырой .py обратно в шаги не разбирается, и
   врать числом было бы хуже, чем промолчать. */
function scenarioStructure(scenario) {
    if (scenario.steps == null) return '';
    const bits = [`${scenario.steps} ${declOfNum(scenario.steps, ['шаг', 'шага', 'шагов'])}`];
    if (scenario.branches) {
        bits.push(`${scenario.branches} ${declOfNum(scenario.branches, ['развилка', 'развилки', 'развилок'])}`);
    }
    return `<div class="meta">${esc(bits.join(' · '))}</div>`;
}

/* Третья строка: итог последних прогонов и непокрытые преграды по пакету
   приложения. uncovered === null значит «пакет не задан в параметрах» —
   тогда бейдж тревог просто не показываем, а не гадаем на нуле. */
function scenarioHealth(scenario) {
    const done = scenario.passed + scenario.failed;
    const bits = [];
    if (done) {
        const tone = scenario.failed ? (scenario.passed ? 'warn' : 'bad') : 'ok';
        bits.push(`<span class="hp ${tone}">✓ ${scenario.passed}/${done}</span>`);
    }
    if (scenario.uncovered) {
        bits.push(`<span class="hp bad">⚠ ${scenario.uncovered} ${
            declOfNum(scenario.uncovered, ['преграда', 'преграды', 'преград'])}</span>`);
    }
    return bits.length ? `<div class="health tnum">${bits.join(' ')}</div>` : '';
}

/* Русское склонение по числу — 1 шаг / 2 шага / 5 шагов. */
function declOfNum(n, forms) {
    const mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return forms[0];
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return forms[1];
    return forms[2];
}

function scenarioCard(scenario) {
    const lastErrorLine = String(scenario.error || '').split('\n').filter(Boolean).pop();
    const mark = scenario.recorded
        ? '<svg class="ic rec-mark"><title>Записано конструктором</title><use href="#i-record"/></svg>'
        : '';
    const drop = scenario.recorded
        ? `<button class="sm danger" title="Удалить сценарий"
             aria-label="Удалить сценарий ${esc(scenario.name)}"
             onclick="event.stopPropagation();deleteScenario('${scenario.key}')">
             <svg class="ic"><use href="#i-trash"/></svg></button>`
        : '';
    /* Правка только у сценариев с рецептом: .py обратно в шаги не
       разбирается (см. GET /api/recorder/recipe). */
    const edit = scenario.editable
        ? `<button class="sm" title="Править шаги в конструкторе"
             aria-label="Править сценарий ${esc(scenario.name)}"
             onclick="event.stopPropagation();editScenario('${scenario.key}')">
             <svg class="ic"><use href="#i-pencil"/></svg></button>`
        : '';
    return `<div class="sc ${S.scenario === scenario.key ? 'on' : ''}"
               onclick="pickScenario('${scenario.key}')">
    <div class="nm">${mark}<span>${esc(scenario.name)}</span>${edit}${drop}</div>
    ${scenarioStructure(scenario)}
    ${scenarioHealth(scenario)}
    ${scenario.description ? `<div class="ds">${esc(scenario.description)}</div>` : ''}
    ${scenario.error ? `<div class="er">${esc(lastErrorLine)}</div>` : ''}
  </div>`;
}
```

- [ ] **Добавить стили**

В `static/css/work.css` после блока `.sc .er { ... }` (строка 31) вставить:

```css
.sc .meta {
    color: var(--dim);
    font-size: 11px;
    margin-top: 2px
}

.sc .health {
    display: flex;
    gap: 8px;
    font-size: 11px;
    margin-top: 2px
}

.sc .hp {
    display: inline-flex;
    align-items: center;
    gap: 3px
}

.sc .hp.ok { color: var(--ok) }
.sc .hp.warn { color: var(--warn) }
.sc .hp.bad { color: var(--bad) }
```

- [ ] **Проверить вручную**

Run: `./run.sh` (или как обычно поднимается сервер — команда та же, что
использует пользователь; не менять)
Открыть `http://localhost:8777/#scen` (порт — как в текущем запущенном
сервере), убедиться:
- у записанного сценария под именем видна строка «N шагов · M развилок»;
- у сценария с параметром `package` виден `✓ passed/done`, и если есть
  необработанные преграды по этому пакету — `⚠ N преград`;
- у сценария, написанного руками (не `editable`), строка структуры не
  показывается вовсе, а не «null шагов».

---

## Task 3: Панель записи — группы «Запись» и «Добавить»

**Files:**
- Modify: `static/index.html:296-341` (первые два `<div class="row">` в `pane-rec`)

**Interfaces:**
- Consumes: ничего нового, только перестановка существующих `onclick`
  (`recStart`, `recPause`, `recLibOpen`, `recAnchorHere`, `recBranchHere`).

### Шаг 3.1: Подписать группы кнопок

- [ ] **Заменить разметку**

В `static/index.html` заменить (строки 296-341, первые два `.row` внутри
`.box` панели записи — третий `.row` со Код/Канвас/Схема/Сохранить трогает
Task 4, здесь не менять):

Было:
```html
                    <div class="box">
                        <div class="row">
                            <button class="sm" id="btnRecStart" onclick="recStart()">
                                <svg class="ic dotrec" aria-hidden="true">
                                    <use href="#i-record"/>
                                </svg>
                                Запись
                            </button>
                            <button class="sm" id="btnRecPause" onclick="recPause()" disabled>
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-pause"/>
                                </svg>
                                Пауза
                            </button>
                            <span class="sp"></span>
                            <span class="stat" id="recState">не записывается</span>
                        </div>
                        <div class="row">
                            <button class="sm accent" onclick="recLibOpen()"
                                    title="Готовые скрипты: открыть приложение, пауза, adb shell…">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-plus"/>
                                </svg>
                                Добавить шаг
                            </button>
                            <button class="sm" id="btnRecAnchor" onclick="recAnchorHere()"
                                    title="Запомнить текущий экран: сценарий проверит, что он на нём, и упадёт внятно, если уехал не туда">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-crosshair"/>
                                </svg>
                                Якорь экрана
                            </button>
                            <button class="sm" id="btnRecBranch" onclick="recBranchHere()"
                                    title="Развилка: «если на экране то-то — выполни блок». Ветка описывает экран, который сейчас на устройстве; остальные добавляются с их экранов">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-layers"/>
                                </svg>
                                Развилка
                            </button>
                            <span class="sp"></span>
                            <label class="kb"
                                   title="Задержки между вашими действиями станут шагами ctx.sleep — сценарий повторит ваш темп. Паузы короче секунды не пишутся.">
                                <input type="checkbox" id="recPauses" onchange="REC.pauses=this.checked">
                                записывать мои паузы
                            </label>
                        </div>
```

Стало:
```html
                    <div class="box">
                        <h3>Запись</h3>
                        <div class="row">
                            <button class="sm" id="btnRecStart" onclick="recStart()">
                                <svg class="ic dotrec" aria-hidden="true">
                                    <use href="#i-record"/>
                                </svg>
                                Запись
                            </button>
                            <button class="sm" id="btnRecPause" onclick="recPause()" disabled>
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-pause"/>
                                </svg>
                                Пауза
                            </button>
                            <span class="sp"></span>
                            <span class="stat" id="recState">не записывается</span>
                        </div>
                        <h3>Добавить в сюжет</h3>
                        <div class="row">
                            <button class="sm accent" onclick="recLibOpen()"
                                    title="Готовые скрипты: открыть приложение, пауза, adb shell…">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-plus"/>
                                </svg>
                                Шаг
                            </button>
                            <button class="sm" id="btnRecAnchor" onclick="recAnchorHere()"
                                    title="Запомнить текущий экран: сценарий проверит, что он на нём, и упадёт внятно, если уехал не туда">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-crosshair"/>
                                </svg>
                                Якорь экрана
                            </button>
                            <button class="sm" id="btnRecBranch" onclick="recBranchHere()"
                                    title="Развилка: «если на экране то-то — выполни блок». Ветка описывает экран, который сейчас на устройстве; остальные добавляются с их экранов">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-layers"/>
                                </svg>
                                Развилка
                            </button>
                            <span class="sp"></span>
                            <label class="kb"
                                   title="Задержки между вашими действиями станут шагами ctx.sleep — сценарий повторит ваш темп. Паузы короче секунды не пишутся.">
                                <input type="checkbox" id="recPauses" onchange="REC.pauses=this.checked">
                                записывать мои паузы
                            </label>
                        </div>
```

(Кнопка «Добавить шаг» переименована в «Шаг» — слово «Добавить» теперь несёт
заголовок группы, повторять его в каждой кнопке группы незачем.)

- [ ] **Проверить вручную**

Открыть экран устройства → вкладка «Запись». Убедиться: над первым рядом
кнопок подпись «ЗАПИСЬ» (капс, мелким моно — стиль уже есть у `.box h3`, тот
же, что у «ПАРАМЕТРЫ» на экране сценариев), над вторым — «ДОБАВИТЬ В СЮЖЕТ».
Все кнопки по-прежнему работают (клик «Запись» стартует запись и т.д.) —
переставлена только разметка, обработчики не менялись.

---

## Task 4: Схема — главный вид вместо канваса

**Files:**
- Modify: `static/index.html` (третий `.row` панели записи; снос блока `#cv`
  строки 553-581; снос `<link>` канваса строка 15; снос `<script>` канваса
  строка 615; новый `#recScheme` рядом с `#recSteps`)
- Modify: `static/js/recorder.js` (`REC.view`, `recSetView`, живая отрисовка
  схемы, снятие ссылок на `CV`)
- Modify: `static/css/recorder.css` (`.sch` — один столбец)
- Delete: `static/js/canvas.js`
- Delete: `static/css/canvas.css`

**Interfaces:**
- Consumes: `schSpine()`, `schSide()`, `schArms()` — уже существуют в
  `recorder.js`, логику хребта/веток не меняем, только точку вызова.
- Consumes: `GET /api/detours?package=...` — уже существующий роут.
- Produces: `REC.view: 'scheme' | 'list'` — читается только внутри
  `recorder.js`, наружу не отдаётся.

### Шаг 4.1: Убрать подключение канваса

- [ ] **Удалить строки в `index.html`**

Удалить строку 15:
```html
    <link rel="stylesheet" href="/static/css/canvas.css">
```

Удалить блок строк 553-582 целиком (комментарий + весь `<div class="cv" id="cv">...</div>` + пустая строка после):
```html
<!-- ============================================================ КАНВАС -->
<!-- Поверх всего, а не внутри панели записи: сборка сюжета требует места,
     а панель шириной в треть экрана его не даёт. Геометрия здесь значима —
     Y это порядок шагов, X это ветвь развилки (см. static/js/canvas.js). -->
<div class="cv" id="cv" hidden>
    <div class="cv-bar">
        <strong>Канвас сценария</strong>
        <span class="cv-hint-bar">по вертикали — порядок шагов, вправо от развилки — её ветви</span>
        <span class="sp"></span>
        <button class="sm" onclick="cvZoomBy(-0.1)" aria-label="Уменьшить">−</button>
        <span class="stat" id="cvZoom">100%</span>
        <button class="sm" onclick="cvZoomBy(0.1)" aria-label="Увеличить">+</button>
        <button class="sm" onclick="cvFit();cvRender()">Вписать</button>
        <button class="primary" onclick="cvClose()">
            <svg class="ic" aria-hidden="true">
                <use href="#i-check"/>
            </svg>
            Готово
        </button>
    </div>
    <div class="cv-body">
        <div class="cv-pal" id="cvPal"></div>
        <div class="cv-stage" id="cvStage" onmousedown="cvStageDown(event)"
             onclick="cvStageClick(event)" onwheel="cvWheel(event)">
            <div class="cv-world" id="cvWorld"></div>
        </div>
        <div class="cv-side" id="cvSide"></div>
    </div>
</div>
```

Удалить строку (после переиндексации где была 615, теперь на ~1 строку выше
из-за удаления `<link>`):
```html
<script src="/static/js/canvas.js"></script>
```

- [ ] **Удалить файлы**

Run: `rm /Users/hlamov.ilya/Desktop/android-farm/static/js/canvas.js /Users/hlamov.ilya/Desktop/android-farm/static/css/canvas.css`

- [ ] **Снять ссылки на `CV` в `recorder.js`**

В `static/js/recorder.js`, в `recSync()` удалить строки (текущие 128-129):
```javascript
    disableWithReason($('btnRecCanvas'), нечего && !S.active,
        'Сначала запишите шаг или откройте устройство');
```

В `recLibAdd()` (текущие строки 996-1008) заменить:

Было:
```javascript
function recLibAdd(preset, values) {
    /* Канвас запомнил, куда уронили пресет, ещё до открытия формы: recPush
       дописывает в конец, а на полотне место выбирает курсор. */
    if (window.CV && CV.on && CV.at != null) {
        const at = CV.at;
        CV.at = null;
        cvInsert(recFill(preset, values), at);
    } else {
        recFill(preset, values).forEach(step => recPush(step));
    }
    closeModal();
    toast(`добавлено: ${preset.title}`, 'ok');
}
```

Стало:
```javascript
function recLibAdd(preset, values) {
    recFill(preset, values).forEach(step => recPush(step));
    closeModal();
    toast(`добавлено: ${preset.title}`, 'ok');
}
```

В `recRender()` (текущие строки 1213-1226) удалить упоминание канваса:

Было:
```javascript
function recRender() {
    /* Канвас рисует тот же REC.steps: изменение из списка, с устройства или
       из бокового редактора канваса обязано быть видно в обоих местах. */
    if (window.CV && CV.on) cvRender();
    const box = $('recSteps');
    if (!box) return;
    if (!REC.steps.length) {
        box.innerHTML = '<div class="empty">Шагов пока нет.<br>'
            + 'Нажмите «● Запись» и кликайте по экрану слева<br>'
            + 'или добавьте готовый шаг из библиотеки.</div>';
        return;
    }
    box.innerHTML = REC.steps.map(recRow).join('');
}
```

Стало (пока без схемы — она добавляется следующим шагом, здесь только
снятие ссылок на канвас):
```javascript
function recRender() {
    const box = $('recSteps');
    if (!box) return;
    if (!REC.steps.length) {
        box.innerHTML = '<div class="empty">Шагов пока нет.<br>'
            + 'Нажмите «● Запись» и кликайте по экрану слева<br>'
            + 'или добавьте готовый шаг из библиотеки.</div>';
        return;
    }
    box.innerHTML = REC.steps.map(recRow).join('');
}
```

- [ ] **Проверить, что канвас нигде больше не упоминается**

Run: `grep -rn "\bCV\b\|cvOpen\|cvRender\|cvClose\|cvFit\|cvInsert\|btnRecCanvas" static/js/*.js static/index.html`
Expected: пусто (0 совпадений)

- [ ] **Проверить вручную**

Открыть экран записи. Кнопка «Канвас» больше не отображается (третий ряд
пока не трогали — она исчезла из JS-проверок, сама кнопка в HTML снимается
следующим шагом вместе с перестройкой ряда). Запись шагов, добавление
пресета из библиотеки работают как раньше.

### Шаг 4.2: Живая схема вместо модалки — состояние и отрисовка

- [ ] **Добавить состояние `REC.view`**

В `static/js/recorder.js`, в объявлении `window.REC` (строки 53-75) добавить
поле после `drag: null,`:

```javascript
    drag: null,       // id шага, который тащат мышью
    view: 'scheme',   // 'scheme' | 'list' — что видно справа от устройства
    schemeTimer: null,
```

- [ ] **Переписать `recSchema()` и `schOpenStep()` под живую панель**

Заменить (текущие строки 690-708, включая комментарий перед `recSchema`):

Было:
```javascript
/* Схема показывает не только то, что вы описали, но и то, что подсунула
   реальность и что ещё не обработано. Из-за этого она список дел, а не
   картинка. */
async function recSchema() {
    let карта = {rules: [], obstacles: []};
    try {
        const пакет = (REC.teach && REC.teach.package) || recGuessPackage();
        карта = await api('/api/detours' + (пакет ? `?package=${encodeURIComponent(пакет)}` : ''));
    } catch (e) {
        toast('карта отводов недоступна: ' + e.message, 'bad');
    }
    $('mTitle').textContent = 'Схема сценария';
    $('mBody').innerHTML = `<div class="sch">
    <div class="sch-spine">${schSpine()}</div>
    <div>${schSide(карта)}</div></div>`;
    $('mActs').innerHTML = '<span class="sp"></span>'
        + '<button class="sm" onclick="closeModal()">Закрыть</button>';
    openModal();
}
```

Стало:
```javascript
/* Схема — постоянная панель, а не модалка: растёт по мере кликов по экрану
   устройства, а не открывается по отдельной команде. Хребет (schSpine) рисуем
   сразу и бесплатно — он строится из REC.steps на месте. Боковая часть
   (schSide — отводы и непокрытые преграды) требует сетевого похода за
   /api/detours и обновляется реже: на переключении вида и после заметных
   изменений записи, а не на каждый клик подряд. */
function recSetView(name) {
    REC.view = name;
    $('recScheme').hidden = name !== 'scheme';
    $('recSteps').hidden = name !== 'list';
    document.querySelectorAll('#recViewToggle .chip').forEach(chip =>
        chip.classList.toggle('on', chip.dataset.view === name));
    if (name === 'scheme') recSchemeRefresh();
}

function recSchemeSpine() {
    const box = document.querySelector('#recScheme .sch-spine');
    if (box) box.innerHTML = schSpine();
}

/* Боковая часть дёргает сеть — не чаще раза в 400мс, даже если recRender()
   зовётся на каждый клик подряд: иначе активная запись била бы по
   /api/detours с той же частотой, что и по экрану устройства. */
function recSchemeRefresh() {
    if (REC.view !== 'scheme') return;
    clearTimeout(REC.schemeTimer);
    REC.schemeTimer = setTimeout(recSchemeSideLoad, 400);
}

async function recSchemeSideLoad() {
    const side = document.querySelector('#recScheme .sch-side-wrap');
    if (!side) return;
    let карта = {rules: [], obstacles: []};
    try {
        const пакет = (REC.teach && REC.teach.package) || recGuessPackage();
        карта = await api('/api/detours' + (пакет ? `?package=${encodeURIComponent(пакет)}` : ''));
    } catch (e) {
        toast('карта отводов недоступна: ' + e.message, 'bad');
        return;
    }
    side.innerHTML = schSide(карта);
}
```

В `schOpenStep()` заменить (текущие строки 640-646) — вместо закрытия
модалки переключаемся на список:

Было:
```javascript
function schOpenStep(id) {
    closeModal();
    REC.open = id;
    recRender();
    const row = document.querySelector('#recSteps .rs.open');
    if (row) row.scrollIntoView({block: 'center', behavior: 'smooth'});
}
```

Стало:
```javascript
function schOpenStep(id) {
    recSetView('list');
    REC.open = id;
    recRender();
    const row = document.querySelector('#recSteps .rs.open');
    if (row) row.scrollIntoView({block: 'center', behavior: 'smooth'});
}
```

- [ ] **Подключить спину схемы к общей перерисовке**

В `recRender()` (после правки в шаге 4.1) добавить вызов отрисовки хребта и
дебаунс-обновление боковой части:

Было:
```javascript
function recRender() {
    const box = $('recSteps');
    if (!box) return;
    if (!REC.steps.length) {
        box.innerHTML = '<div class="empty">Шагов пока нет.<br>'
            + 'Нажмите «● Запись» и кликайте по экрану слева<br>'
            + 'или добавьте готовый шаг из библиотеки.</div>';
        return;
    }
    box.innerHTML = REC.steps.map(recRow).join('');
}
```

Стало:
```javascript
function recRender() {
    recSchemeSpine();
    recSchemeRefresh();
    const box = $('recSteps');
    if (!box) return;
    if (!REC.steps.length) {
        box.innerHTML = '<div class="empty">Шагов пока нет.<br>'
            + 'Нажмите «● Запись» и кликайте по экрану слева<br>'
            + 'или добавьте готовый шаг из библиотеки.</div>';
        return;
    }
    box.innerHTML = REC.steps.map(recRow).join('');
}
```

### Шаг 4.3: Разметка — панель схемы и переключатель вида

- [ ] **Заменить третий `.row` и контейнер `#recSteps` в `index.html`**

Было (текущие строки 342-381, третий `.row` внутри `.box` + `#recSteps`):
```html
                        <div class="row">
                            <button class="sm" id="btnRecCode" onclick="recPreview()">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-code"/>
                                </svg>
                                Код
                            </button>
                            <button class="sm" id="btnRecCanvas" onclick="cvOpen()"
                                    title="Канвас: собрать сюжет мышью — порядок шагов по вертикали, ветви развилки вправо">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-grid"/>
                                </svg>
                                Канвас
                            </button>
                            <button class="sm" id="btnRecSchema" onclick="recSchema()"
                                    title="Список дел: отводы и преграды, которые ферма ещё не умеет обходить">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-layers"/>
                                </svg>
                                Схема
                            </button>
                            <span class="sp"></span>
                            <button class="sm" id="btnRecModeOff" onclick="recModeOff()"
                                    title="Выйти из обучения, не сохраняя отвод" hidden>
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-undo"/>
                                </svg>
                                <span>Не учить</span>
                            </button>
                            <button class="primary" id="btnRecSave" onclick="recSaveForm()">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-save"/>
                                </svg>
                                <span>Сохранить сценарий</span>
                            </button>
                        </div>
                        <div class="warn" id="recBanner" hidden></div>
                    </div>
                    <div class="scroll" id="recSteps"></div>
                </div>
```

Стало:
```html
                        <h3>Вид</h3>
                        <div class="row" id="recViewToggle">
                            <button class="chip on" data-view="scheme" onclick="recSetView('scheme')">Схема</button>
                            <button class="chip" data-view="list" onclick="recSetView('list')">Список</button>
                            <button class="sm" id="btnRecCode" onclick="recPreview()">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-code"/>
                                </svg>
                                Код
                            </button>
                            <span class="sp"></span>
                            <button class="sm" id="btnRecModeOff" onclick="recModeOff()"
                                    title="Выйти из обучения, не сохраняя отвод" hidden>
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-undo"/>
                                </svg>
                                <span>Не учить</span>
                            </button>
                            <button class="primary" id="btnRecSave" onclick="recSaveForm()">
                                <svg class="ic" aria-hidden="true">
                                    <use href="#i-save"/>
                                </svg>
                                <span>Сохранить сценарий</span>
                            </button>
                        </div>
                        <div class="warn" id="recBanner" hidden></div>
                    </div>
                    <div class="scroll sch" id="recScheme">
                        <div class="sch-spine"></div>
                        <div class="sch-side-wrap"></div>
                    </div>
                    <div class="scroll" id="recSteps" hidden></div>
                </div>
```

(Кнопка «Схема» пропала как отдельная — её работу теперь делает чип
«Схема», уже активный по умолчанию (`class="chip on"`), согласованный с
`REC.view = 'scheme'` в JS.)

- [ ] **Один столбец вместо двух в `.sch`**

В `static/css/recorder.css` заменить строку 130:

Было:
```css
.sch { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: var(--s4); }
```

Стало:
```css
.sch { display: flex; flex-direction: column; gap: var(--s4); padding: var(--s3); }
```

(Раньше `.sch` жила в модалке шириной в пол-экрана — два столбца помещались.
Теперь это правая колонка панели записи, вдвое уже: хребет и боковая часть
идут друг под другом.)

- [ ] **Инициализировать вид при открытии панели записи**

Найти в `recorder.js` функцию, вызываемую при открытии конструктора
(`recOpen`), и добавить сброс вида в начало записи. Сначала найти сигнатуру:

Run: `grep -n "^function recOpen\|^async function recOpen" static/js/recorder.js`

Затем в начало тела `recOpen` (после существующих присвоений `REC.*`, перед
первым вызовом `recRender()` или `recSync()`, если он там есть) добавить:
```javascript
    REC.view = 'scheme';
```

Если `recOpen` уже вызывает `recRender()` в конце — этого достаточно: панель
схемы нарисуется вместе со всем остальным. Если нет — добавить вызов
`recSetView('scheme')` вместо голого присвоения, чтобы применились и CSS
`hidden`, и подсветка чипа.

- [ ] **Проверить вручную**

1. Открыть устройство → «Запись». Справа по умолчанию видна «Схема» —
   пустая, с подсказкой «Шагов пока нет — записывать нечего».
2. Нажать «● Запись», кликнуть пару раз по экрану слева. Хребет схемы растёт
   с каждым кликом без перезагрузки страницы.
3. Нажать «Развилка» — на схеме появляется ветка (`◇`) вбок от узла.
4. Переключиться на чип «Список» — видна старая редактируемая построчная
   разметка со стрелками/удалением/перетаскиванием, как раньше. Переключиться
   обратно на «Схема» — хребет на месте, ничего не потеряно (`REC.steps` один
   источник правды для обоих видов).
5. Нажать «Код» — открывается модалка со сгенерированным `.py`, как раньше
   (это поведение не менялось).
6. Кликнуть по узлу на схеме — переключает на «Список» и прокручивает к
   этому шагу (было: открывало модалку; проверить, что новое поведение не
   ломает редактирование — шаг действительно раскрывается для правки).
7. Открыть DevTools → Network, постоять на схеме без кликов 5 секунд —
   не должно быть повторяющихся запросов к `/api/detours` (только один, при
   переключении на вид).

---

## Self-Review

**Spec coverage:**
- Раздел 1 спека (карточка сценария: структура + здоровье) → Task 1 (бэкенд)
  + Task 2 (фронт). ✓
- Раздел 2 (устройство + схема рядом) → Task 4. ✓
- Раздел 3 (группы вместо ряда кнопок) → Task 3 (Запись/Добавить) + Task 4,
  шаг 4.3 (Вид). ✓
- Раздел 4 (визуальный язык схемы не меняется) → Task 4 переиспользует
  `schSpine`/`schArms`/`schSide` без изменения их вывода, меняется только
  точка вызова (панель вместо модалки). ✓
- «Не-цели» (без свободного холста, без переноса «Запустить», без новой
  палитры, без переименования Развилка/Якорь) — план не нарушает ни одного
  пункта. ✓

**Type consistency:** `scan_obstacles(package: str = "") -> list` в Task 1
шаг 1.1 — та же сигнатура используется в Task 1 шаг 1.3 (`_uncovered`) и в
`detour_map`. `Runner.scenario_stats(key: str, limit: int = 50) -> dict` с
ключами `passed`/`failed` — так же читается в `list_scenarios`. `REC.view`
пишется и читается только строками `'scheme'`/`'list'` во всех местах
(`recSetView`, `recSchemeRefresh`, HTML `data-view`). Совпадает везде.

**Placeholder scan:** плейсхолдеров, «TODO», «добавить обработку ошибок» без
кода — нет, весь код в шагах полный.

**Порядок задач:** Task 1 не зависит от 2-4. Task 2 зависит от Task 1 (поля
в ответе API). Task 3 не зависит ни от кого (чистая перестановка разметки).
Task 4 не зависит от 2-3, но логически идёт последним — самый рискованный
кусок, и к моменту его начала карточки сценариев и раскладка тулбара уже
причёсаны, легче отличать регрессии Task 4 от старых огрехов.
