# Функции из Laixi (F1–F9) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в ферму девять функций, которых нет, но есть у Laixi: единое разрешение, пакетный ввод «каждому своё», горячие клавиши фраз, окно «Инструменты» (здоровье, уведомления, резервная копия, документация API, черновик по описанию) и контакты пакетом.

**Architecture:** Чистая логика (разбор вывода adb, формирование команд, разбор файлов) в отдельных модулях без adb и диска, с тестами на образцах вывода. Действия над телефонами добавляются в таблицу `screen.ACTIONS` (её же использует `bulk.ACTIONS`). Общие для фермы функции живут в новом окне «Инструменты» (кнопка в шапке), каждая регистрирует себя через `toolsRegister`.

**Tech Stack:** Python 3.9+, FastAPI (функции роутера зовутся в тестах напрямую), pytest, чистый JS без сборки, Node для JS-тестов.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-10-25-ready-stories-design.md`, часть 2. Отступления от неё, найденные при чтении кода (они здесь главные):
  - **F3:** отдельный `GET /api/devices/health` не нужен. Реестр уже опрашивает заряд и температуру каждые `HEALTH_INTERVAL` секунд и отдаёт их в `/api/devices`; мы добавляем в тот же опрос RAM/ROM/CPU, а таблица строится из уже опрашиваемого списка. Тревога «перегрев» уже есть (`TEMP_ALERT_C`).
  - **F7:** в ферме уже есть 101 маршрут `/api/*`, интерактивная справка `/docs` и защита `FARM_TOKEN` с заголовком `X-Farm-Token` (`farm/security.py`). Отдельные «публичные» маршруты и второй токен не нужны: делается документация `docs/public-api.md` с проверкой, что все упомянутые в ней маршруты существуют.
  - **F8:** горячие клавиши работают в окне массовых действий (в пульте у телефона нет выбранных телефонов и списка фраз); фразы в ферме — плоский список в `localStorage` (`farm.phrases`), а не группы.
  - **F2:** выгрузка резервной копии — `POST` (проверяется Origin), а не `GET`: в архиве может лежать приватный ключ adb.
- Python `>=3.9`: аннотации `X | None` только с `from __future__ import annotations`; без `match`.
- Комментарии и сообщения пользователю на русском, простыми словами; комментарии объясняют «почему».
- Чистые модули без adb, диска и FastAPI; случайное через параметр `rng`.
- Тесты не требуют телефона; из `backend/`: `python -m pytest tests/<файл> -q`. Роутеры в тестах вызываются как функции (`TestClient` в проекте не используется).
- Выполнять задачи по порядку: Task 2, 3, 4 и 11 правят `frontend/js/bulk.js` и `frontend/index.html`, поэтому параллельно их не гнать.
- Не коммитить чужие правки: в рабочем дереве есть незакоммиченные файлы владельца (`frontend/index.html`, `frontend/strings/ru.json`, `frontend/js/addstep.js`, `frontend/js/recorder.js`, `frontend/css/recorder.css`, `backend/tests/test_addstep_js.py`). Работа ведётся в отдельном git worktree от `main`; `git add` только по именам файлов задачи.
- Функции, которые я не мог проверить на телефоне (F1, F5, F6), в интерфейсе помечены «проверьте на одном телефоне».
- Не берём: массовые рассылки сообщений, P2P-доступ, хаб AndroidsBox.

---

## File Structure

| Файл | Ответственность |
|---|---|
| `backend/farm/control/display.py` (новый) | разбор `wm size`/`wm density`, команды, пропорции |
| `backend/farm/lines.py` (новый) | строки файла → текст каждому телефону |
| `backend/farm/health.py` (новый) | разбор `/proc/meminfo`, `df`, `/proc/stat` |
| `backend/farm/backup.py`, `backend/farm/api/backup.py` (новые) | резервная копия и восстановление |
| `backend/farm/notifications.py`, `backend/farm/api/notifications.py` (новые) | разбор `dumpsys notification`, список отслеживаемых |
| `backend/farm/contacts.py` (новый) | номера, разбор файла, shell-скрипты контактов |
| `backend/farm/vlm/plan.py` (новый) | черновик сценария из текста |
| `backend/farm/api/screen.py` | действия `resolution_set`, `resolution_reset`, `contacts_add`, `contacts_clear` |
| `backend/farm/api/bulk.py` | `POST /api/bulk/display`, `POST /api/bulk/text_lines` |
| `backend/farm/devices/registry.py`, `backend/farm/config.py`, `backend/farm/adb.py` | RAM/ROM/CPU в опросе здоровья и тревоги |
| `backend/farm/api/vlm.py`, `backend/farm/api/__init__.py` | маршрут плана, подключение роутеров |
| `frontend/js/bulk.js` | панели «Разрешение», «Каждому своё», «Контакты», горячие клавиши F1–F9 |
| `frontend/js/tools.js`, `frontend/css/tools.css` (новые) | окно «Инструменты» и общий реестр |
| `frontend/js/tool-health.js`, `tool-notify.js`, `tool-backup.js`, `tool-api.js`, `tool-draft.js` (новые) | вкладки инструментов |
| `frontend/index.html`, `frontend/strings/ru.json` | кнопка в шапке, подключение скриптов |
| `docs/public-api.md` (новый), `README.md`, `docs/guide.md`, `.claude/skills/farm-ux/SKILL.md` | документация |

---

### Task 1: `control/display.py` — разбор и команды разрешения

**Files:**
- Create: `backend/farm/control/display.py`
- Test: `backend/tests/test_display.py`

**Interfaces:**
- Produces:
  - `parse_wm_size(out: str) -> dict` — `{"physical": (w, h)|None, "override": (w, h)|None, "current": (w, h)|None}`
  - `parse_density(out: str) -> dict` — те же ключи, значения `int|None`
  - `size_command(width: int, height: int) -> str`, `density_command(dpi: int) -> str` (бросают `ValueError` с русским текстом)
  - `RESET_COMMANDS = ("wm size reset", "wm density reset")`
  - `fit_height(width: int, height: int, new_width: int) -> int` (чётное)
  - `summarize(sizes: list) -> list[dict]` — `[{"size": (w, h), "count": n}]` по убыванию `count`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_display.py`:

```python
"""Разрешение и плотность: разбор wm, команды, пропорции, сводка по телефонам."""
import pytest

from farm.control import display


def test_parse_wm_size_physical_only():
    assert display.parse_wm_size("Physical size: 1080x2400\n") == {
        "physical": (1080, 2400), "override": None, "current": (1080, 2400)}


def test_parse_wm_size_override_wins_as_current():
    got = display.parse_wm_size("Physical size: 1080x2400\nOverride size: 720x1600\n")
    assert got["physical"] == (1080, 2400)
    assert got["override"] == (720, 1600)
    assert got["current"] == (720, 1600)


def test_parse_wm_size_garbage_and_empty():
    for text in ("", None, "error: closed", "Physical size: ?x?"):
        assert display.parse_wm_size(text)["current"] is None


def test_parse_density():
    assert display.parse_density("Physical density: 420\n") == {
        "physical": 420, "override": None, "current": 420}
    got = display.parse_density("Physical density: 420\nOverride density: 320\n")
    assert got["current"] == 320 and got["physical"] == 420
    assert display.parse_density("")["current"] is None


def test_size_command_ok():
    assert display.size_command(720, 1600) == "wm size 720x1600"
    assert display.size_command("720", "1600.0") == "wm size 720x1600"


@pytest.mark.parametrize("w,h", [(100, 1600), (720, 100), (5000, 1600), (720, 9000), ("abc", 1)])
def test_size_command_rejects_out_of_range(w, h):
    with pytest.raises(ValueError) as e:
        display.size_command(w, h)
    assert "320" in str(e.value) and "4000" in str(e.value)


def test_density_command():
    assert display.density_command(320) == "wm density 320"
    for bad in (10, 5000, "x"):
        with pytest.raises(ValueError):
            display.density_command(bad)


def test_reset_commands():
    assert display.RESET_COMMANDS == ("wm size reset", "wm density reset")


def test_fit_height_keeps_ratio_and_is_even():
    assert display.fit_height(1080, 2400, 720) == 1600
    assert display.fit_height(1080, 2340, 720) == 1560
    assert display.fit_height(1080, 2401, 720) % 2 == 0


def test_summarize_groups_and_sorts():
    got = display.summarize([(1080, 2400), (720, 1600), (1080, 2400), None, (1080, 2400)])
    assert got == [{"size": (1080, 2400), "count": 3}, {"size": (720, 1600), "count": 1}]
    assert display.summarize([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_display.py -q`
Expected: FAIL `ImportError: cannot import name 'display' from 'farm.control'`.

- [ ] **Step 3: Implement**

Create `backend/farm/control/display.py`:

```python
"""Разрешение и плотность экрана: разбор `wm size`/`wm density` и команды.

Чистый модуль: ни adb, ни диска. Зачем: записанные клики и сценарии на долях
экрана попадают в одни и те же места, только если у всех телефонов одинаковые
размер и плотность. Смена обратима (`wm size reset`), поэтому её можно
пробовать.
"""
from __future__ import annotations

import re
from collections import Counter

MIN_SIDE, MAX_SIDE = 320, 4000
MIN_DPI, MAX_DPI = 80, 800

_SIZE = re.compile(r"(Physical|Override) size:\s*(\d+)x(\d+)", re.I)
_DENSITY = re.compile(r"(Physical|Override) density:\s*(\d+)", re.I)

RESET_COMMANDS = ("wm size reset", "wm density reset")


def parse_wm_size(out) -> dict:
    """Вывод `wm size`: физический размер, подмена (override) и действующий."""
    found = {kind.lower(): (int(w), int(h)) for kind, w, h in _SIZE.findall(out or "")}
    physical, override = found.get("physical"), found.get("override")
    return {"physical": physical, "override": override, "current": override or physical}


def parse_density(out) -> dict:
    """Вывод `wm density`: то же, что parse_wm_size, но числом."""
    found = {kind.lower(): int(v) for kind, v in _DENSITY.findall(out or "")}
    physical, override = found.get("physical"), found.get("override")
    return {"physical": physical, "override": override, "current": override or physical}


def _int(value, what):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        raise ValueError(what)


def size_command(width, height) -> str:
    text = f"ширина и высота — числа от {MIN_SIDE} до {MAX_SIDE}"
    w, h = _int(width, text), _int(height, text)
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
        raise ValueError(text)
    return f"wm size {w}x{h}"


def density_command(dpi) -> str:
    text = f"плотность — число от {MIN_DPI} до {MAX_DPI}"
    n = _int(dpi, text)
    if not MIN_DPI <= n <= MAX_DPI:
        raise ValueError(text)
    return f"wm density {n}"


def fit_height(width, height, new_width) -> int:
    """Высота при новой ширине с теми же пропорциями; чётная, как требует экран."""
    return int(round(new_width * height / width / 2.0)) * 2


def summarize(sizes) -> list:
    """Сколько телефонов с каждым размером — по убыванию. None пропускается."""
    counts = Counter(tuple(s) for s in sizes if s)
    return [{"size": size, "count": n} for size, n in counts.most_common()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_display.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/farm/control/display.py backend/tests/test_display.py
git commit -m "F1: разбор и команды разрешения экрана (control/display.py)"
```

---

### Task 2: F1 — действия, сводка и панель «Разрешение»

**Files:**
- Modify: `backend/farm/api/screen.py` (импорт и функции перед `ACTIONS = {`, строка ~135; записи в `ACTIONS`), `backend/farm/api/bulk.py` (новый маршрут), `frontend/js/bulk.js` (плитка в `bulkMenu`, панель в `bulkPanel`, функции)
- Test: `backend/tests/test_resolution_actions.py`, `backend/tests/test_bulk_resolution_js.py`

**Interfaces:**
- Consumes (Task 1): `display.size_command, display.density_command, display.RESET_COMMANDS, display.parse_wm_size, display.parse_density`.
- Produces:
  - `screen.ACTIONS["resolution_set"]` — тело `{type, width, height, density?}`; `screen.ACTIONS["resolution_reset"]`
  - `bulk._display_info(serial) -> dict` — `{"size": [w,h]|None, "physical": [w,h]|None, "overridden": bool, "density": int|None, "physical_density": int|None}`
  - `POST /api/bulk/display` тело `{"serials": [...]}` → стандартная сводка `_each`
  - JS: `bulkResSummary(results) -> [{size: "1080×2400", count: n}]`, `bulkResFit(w, h, newW) -> int`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_resolution_actions.py`:

```python
"""Действия смены разрешения и чтение текущего размера с телефонов."""
import pytest

from farm.api import bulk, screen


@pytest.fixture
def shell(monkeypatch):
    calls = []
    monkeypatch.setattr(screen.adb, "shell",
                        lambda serial, cmd, timeout=None: calls.append((serial, cmd)) or "")
    forgot = []
    monkeypatch.setattr(screen.control, "forget_size", lambda serial: forgot.append(serial))
    return calls, forgot


def test_resolution_set_runs_wm_and_forgets_cached_size(shell):
    calls, forgot = shell
    screen.ACTIONS["resolution_set"]("S1", {"type": "resolution_set", "width": 720,
                                            "height": 1600, "density": 320})
    assert calls == [("S1", "wm size 720x1600"), ("S1", "wm density 320")]
    assert forgot == ["S1"]


def test_resolution_set_without_density_skips_it(shell):
    calls, _ = shell
    screen.ACTIONS["resolution_set"]("S1", {"width": 720, "height": 1600, "density": ""})
    assert calls == [("S1", "wm size 720x1600")]


def test_resolution_set_rejects_bad_values_before_touching_the_phone(shell):
    calls, _ = shell
    with pytest.raises(ValueError):
        screen.ACTIONS["resolution_set"]("S1", {"width": 50, "height": 1600})
    with pytest.raises(ValueError):
        screen.ACTIONS["resolution_set"]("S1", {})
    assert calls == []


def test_resolution_reset(shell):
    calls, forgot = shell
    screen.ACTIONS["resolution_reset"]("S1", {"type": "resolution_reset"})
    assert calls == [("S1", "wm size reset"), ("S1", "wm density reset")]
    assert forgot == ["S1"]


def test_bulk_uses_same_table():
    assert "resolution_set" in bulk.ACTIONS and bulk.ACTIONS is screen.ACTIONS


def test_display_info_reads_size_and_density(monkeypatch):
    answers = {
        "wm size": "Physical size: 1080x2400\nOverride size: 720x1600\n",
        "wm density": "Physical density: 420\nOverride density: 320\n",
    }
    monkeypatch.setattr(bulk.adb, "shell", lambda serial, cmd, timeout=None: answers[cmd])
    assert bulk._display_info("S1") == {
        "size": [720, 1600], "physical": [1080, 2400], "overridden": True,
        "density": 320, "physical_density": 420}


def test_display_info_not_overridden(monkeypatch):
    answers = {"wm size": "Physical size: 1080x2400\n", "wm density": "Physical density: 420\n"}
    monkeypatch.setattr(bulk.adb, "shell", lambda serial, cmd, timeout=None: answers[cmd])
    got = bulk._display_info("S1")
    assert got["overridden"] is False and got["size"] == [1080, 2400]


def test_bulk_display_endpoint_summarises_each_phone(monkeypatch):
    monkeypatch.setattr(bulk, "_online", lambda serials: list(serials))
    monkeypatch.setattr(bulk, "_display_info", lambda s: {"size": [1080, 2400]})
    got = bulk.bulk_display(serials=["A", "B"])
    assert got["done"] == 2 and got["results"]["A"]["size"] == [1080, 2400]
```

Create `backend/tests/test_bulk_resolution_js.py`:

```python
"""Панель «Разрешение»: сводка по размерам и пропорции (bulk.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* разрешение: начало */'), b = src.indexOf('/* разрешение: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.sum=bulkResSummary;this.fit=bulkResFit', ctx);
const got = ctx.sum({
  A: {ok: true, size: [1080, 2400]}, B: {ok: true, size: [720, 1600]},
  C: {ok: true, size: [1080, 2400]}, D: {ok: false, error: 'offline'}, E: {ok: true, size: null},
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(got)),
  [{size: '1080×2400', count: 2, w: 1080, h: 2400}, {size: '720×1600', count: 1, w: 720, h: 1600}]);
assert.deepStrictEqual(ctx.sum(null), []);
assert.strictEqual(ctx.fit(1080, 2400, 720), 1600);
assert.strictEqual(ctx.fit(1080, 2340, 720), 1560);
"""


def test_resolution_helpers():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_resolution_actions.py tests/test_bulk_resolution_js.py -q`
Expected: FAIL (`KeyError: 'resolution_set'`, нет маркеров в `bulk.js`).

- [ ] **Step 3: Implement backend**

`backend/farm/api/screen.py`: у импортов добавить `from ..control import display`. Перед `ACTIONS = {` вставить:

```python
def _resolution_set(serial, p):
    """Размер (и плотность) экрана одинаковые на всех телефонах — чтобы
    записанные клики попадали в те же места. Сначала проверка чисел, потом
    телефон: кривой запрос не должен оставить экран наполовину переставленным."""
    commands = [display.size_command(p.get("width"), p.get("height"))]
    if p.get("density") not in (None, ""):
        commands.append(display.density_command(p.get("density")))
    for cmd in commands:
        adb.shell(serial, cmd, timeout=SHELL_TIMEOUT)
    control.forget_size(serial)   # кэш размера устарел: тапы по нему попадали бы мимо
    return {"ok": True}


def _resolution_reset(serial, p):
    for cmd in display.RESET_COMMANDS:
        adb.shell(serial, cmd, timeout=SHELL_TIMEOUT)
    control.forget_size(serial)
    return {"ok": True}
```

и добавить в словарь `ACTIONS` две строки:

```python
    "resolution_set": _resolution_set,
    "resolution_reset": _resolution_reset,
```

`backend/farm/api/bulk.py`: добавить `from ..control import display` к импортам и после `bulk_warm` (около строки 270) вставить:

```python
def _display_info(serial: str) -> dict:
    """Текущий размер и плотность одного телефона для сводки «у вас N разных»."""
    size = display.parse_wm_size(adb.shell(serial, "wm size", timeout=10))
    dens = display.parse_density(adb.shell(serial, "wm density", timeout=10))
    as_list = lambda v: list(v) if v else None  # noqa: E731
    return {"size": as_list(size["current"]), "physical": as_list(size["physical"]),
            "overridden": size["override"] is not None or dens["override"] is not None,
            "density": dens["current"], "physical_density": dens["physical"]}


@router.post("/display")
def bulk_display(serials: list[str] = Body(..., embed=True)):
    """Размер и плотность выбранных телефонов: окно «Разрешение» показывает,
    есть ли среди них разные, до того как что-то менять."""
    return _each(_online(serials), _display_info, serials)
```

- [ ] **Step 4: Implement frontend**

`frontend/js/bulk.js`: перед `function bulkMenu()` добавить блок с маркерами:

```javascript
/* разрешение: начало */
/* Разрешение и плотность: у всех выбранных одинаковые, чтобы записанные
   клики попадали в одни и те же места. */
function bulkResSummary(results) {
    const groups = new Map();
    for (const r of Object.values(results || {})) {
        if (!r || !r.ok || !r.size) continue;
        const key = `${r.size[0]}×${r.size[1]}`;
        const g = groups.get(key) || {size: key, count: 0, w: r.size[0], h: r.size[1]};
        g.count += 1;
        groups.set(key, g);
    }
    return [...groups.values()].sort((a, b) => b.count - a.count);
}

function bulkResFit(w, h, newW) {
    return Math.round(newW * h / w / 2) * 2;
}
/* разрешение: конец */

const BULK_RES = {base: null};

async function bulkResLoad() {
    const info = $('bulkResInfo');
    try {
        const res = await post('/api/bulk/display', {serials: bulkTargets()});
        const groups = bulkResSummary(res.results);
        BULK_RES.base = groups[0] || null;
        info.textContent = groups.length
            ? 'Сейчас: ' + groups.map(g => `${g.size} — ${g.count}`).join(', ')
                + (groups.length > 1 ? ` · у вас ${groups.length} разных размера` : '')
            : 'Размер телефонов узнать не удалось';
        if (BULK_RES.base) {
            $('bulkResW').value = BULK_RES.base.w;
            $('bulkResH').value = BULK_RES.base.h;
        }
    } catch (e) {
        info.textContent = e.message;
    }
}

function bulkResWidthChanged() {
    const base = BULK_RES.base;
    if (!base || !$('bulkResKeep').checked) return;
    const w = Number($('bulkResW').value);
    if (w > 0) $('bulkResH').value = bulkResFit(base.w, base.h, w);
}

function bulkResApply() {
    const width = Number($('bulkResW').value), height = Number($('bulkResH').value);
    const density = $('bulkResD').value.trim();
    if (!width || !height) return toast('впишите ширину и высоту', 'bad');
    bulkAction({type: 'resolution_set', width, height, density}, 'Разрешение');
}

function bulkResReset() {
    bulkAction({type: 'resolution_reset'}, 'Вернуть разрешение');
}
```

В `bulkMenu`, в группу «Управление», после плитки «Подготовить» добавить:

```javascript
      ${tile("bulkPanel('res')", 'grid', 'Разрешение', 'одинаковое на всех, чтобы клики попадали', 'res')}
```

В `bulkPanel`, в объект `box.innerHTML = {...}[kind]`, добавить ключ:

```javascript
        res: `<small class="dim" id="bulkResInfo">считаю размеры…</small>
          <div class="bp-row">
            <input id="bulkResW" type="number" min="320" max="4000" placeholder="ширина" aria-label="Ширина"
                   oninput="bulkResWidthChanged()">
            <span>×</span>
            <input id="bulkResH" type="number" min="320" max="4000" placeholder="высота" aria-label="Высота">
            <input id="bulkResD" type="number" min="80" max="800" placeholder="плотность (необязательно)" aria-label="Плотность">
          </div>
          <div class="bp-row">
            <label><input type="checkbox" id="bulkResKeep" checked> сохранить пропорции</label>
            <button class="sm primary" onclick="bulkResApply()">Применить</button>
            <button class="sm" onclick="bulkResReset()">Вернуть как было</button></div>
          <small class="dim">Проверьте на одном телефоне: на некоторых прошивках после смены обрывается трансляция экрана — «Вернуть как было» всегда доступно.</small>`,
```

и после строки `if (kind === 'app') bulkLoadApps();` добавить `if (kind === 'res') bulkResLoad();`.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_resolution_actions.py tests/test_bulk_resolution_js.py tests/test_display.py tests/test_strings.py -q`
Expected: all PASS.

```bash
git add backend/farm/api/screen.py backend/farm/api/bulk.py frontend/js/bulk.js backend/tests/test_resolution_actions.py backend/tests/test_bulk_resolution_js.py
git commit -m "F1: массовое действие «Разрешение» и сводка размеров"
```

---

### Task 3: F4 — пакетный ввод «каждому своё»

**Files:**
- Create: `backend/farm/lines.py`
- Modify: `backend/farm/api/bulk.py` (маршрут), `frontend/js/bulk.js` (плитка, панель, функции)
- Test: `backend/tests/test_lines.py`, `backend/tests/test_bulk_lines_js.py`

**Interfaces:**
- Produces:
  - `lines.clean_rows(raw, limit=5000) -> list[str]` — `raw` список строк или текст
  - `lines.split_row(row: str, separator: str) -> list[str]`
  - `lines.render(template: str, fields: list[str]) -> str` — `{1}`, `{2}`… подставляются; пустой шаблон → вся строка
  - `lines.assign(serials: list[str], rows: list[str], mode: str, rng=None) -> dict[str, str | None]` — режимы `"order"`, `"cycle"`, `"random"`; `None` — строки не хватило
  - `bulk.text_lines(serials, lines, mode, separator, template, clear) -> dict` (сводка `_each`)
  - JS `bulkLinesRows(text) -> string[]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_lines.py`:

```python
"""Пакетный ввод «каждому своё»: строки → телефоны, части строки, шаблон."""
import random

import pytest

from farm import lines
from farm.api import bulk


def test_clean_rows_from_text_and_list():
    assert lines.clean_rows("a\n\n  b \r\nc") == ["a", "b", "c"]
    assert lines.clean_rows([" x ", "", "y"]) == ["x", "y"]
    assert lines.clean_rows(None) == []


def test_clean_rows_limit():
    assert len(lines.clean_rows([str(i) for i in range(9000)])) == lines.MAX_ROWS


def test_split_row():
    assert lines.split_row("ivan;pass1;x", ";") == ["ivan", "pass1", "x"]
    assert lines.split_row(" a , b ", ",") == ["a", "b"]
    assert lines.split_row("whole line", "") == ["whole line"]


def test_render_template():
    assert lines.render("{1}@mail.ru", ["ivan", "p"]) == "ivan@mail.ru"
    assert lines.render("{2}/{1}", ["a", "b"]) == "b/a"
    assert lines.render("{3}", ["a"]) == ""            # части нет — пусто, а не падение
    assert lines.render("", ["whole"]) == "whole"


def test_assign_order_leaves_extra_phones_without_text():
    got = lines.assign(["A", "B", "C"], ["1", "2"], "order")
    assert got == {"A": "1", "B": "2", "C": None}


def test_assign_cycle_repeats():
    got = lines.assign(["A", "B", "C", "D", "E"], ["1", "2"], "cycle")
    assert [got[s] for s in "ABCDE"] == ["1", "2", "1", "2", "1"]


def test_assign_random_uses_only_given_rows():
    got = lines.assign(["A", "B", "C", "D"], ["x", "y"], "random", random.Random(3))
    assert set(got.values()) <= {"x", "y"}


def test_assign_unknown_mode():
    with pytest.raises(ValueError):
        lines.assign(["A"], ["1"], "weird")


def test_assign_without_rows():
    assert lines.assign(["A", "B"], [], "order") == {"A": None, "B": None}


@pytest.fixture
def sent(monkeypatch):
    got = []
    monkeypatch.setattr(bulk, "_online", lambda serials: list(serials))
    monkeypatch.setitem(bulk.ACTIONS, "text",
                        lambda serial, p: got.append((serial, p["value"], p.get("clear"))))
    return got


def test_endpoint_sends_each_phone_its_line(sent):
    res = bulk.text_lines(serials=["A", "B"], lines=["one", "two"], mode="order",
                          separator="", template="", clear=False)
    assert sorted(sent) == [("A", "one", False), ("B", "two", False)]
    assert res["done"] == 2 and res["failed"] == 0


def test_endpoint_template_and_separator(sent):
    bulk.text_lines(serials=["A"], lines=["ivan;secret"], mode="order",
                    separator=";", template="{1}@x.ru", clear=True)
    assert sent == [("A", "ivan@x.ru", True)]


def test_endpoint_reports_phones_without_a_line(sent):
    res = bulk.text_lines(serials=["A", "B", "C"], lines=["one"], mode="order",
                          separator="", template="", clear=False)
    assert [s for s, _, _ in sent] == ["A"]
    assert res["failed"] == 2
    assert "не хватило" in res["results"]["B"]["error"]


def test_endpoint_rejects_empty_file(sent):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        bulk.text_lines(serials=["A"], lines=["", "  "], mode="order",
                        separator="", template="", clear=False)
    assert e.value.status_code == 400
```

Create `backend/tests/test_bulk_lines_js.py`:

```python
"""Панель «Каждому своё»: разбор строк файла и предпросмотр (bulk.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* строки: начало */'), b = src.indexOf('/* строки: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.rows=bulkLinesRows;this.plan=bulkLinesPlan', ctx);
assert.deepStrictEqual(ctx.rows(' a \n\nb\r\n c '), ['a', 'b', 'c']);
assert.strictEqual(ctx.rows('x\n'.repeat(9000)).length, 5000);
const plan = ctx.plan(['Т1', 'Т2', 'Т3'], ['one', 'two'], 'order');
assert.deepStrictEqual(JSON.parse(JSON.stringify(plan)), [
  {name: 'Т1', text: 'one'}, {name: 'Т2', text: 'two'}, {name: 'Т3', text: null}]);
const cyc = ctx.plan(['Т1', 'Т2', 'Т3'], ['one', 'two'], 'cycle');
assert.deepStrictEqual(cyc.map(x => x.text), ['one', 'two', 'one']);
"""


def test_lines_helpers():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_lines.py tests/test_bulk_lines_js.py -q`
Expected: FAIL `ImportError: cannot import name 'lines' from 'farm'`.

- [ ] **Step 3: Implement backend**

Create `backend/farm/lines.py`:

```python
"""Пакетный ввод «каждому своё»: строка файла — на свой телефон.

Чистый модуль, как phrases.py. Зачем: у каждого телефона свой логин, свой
текст или ссылка; одинаковый текст на сорока телефонах — готовый признак
автоматизации. Режимы: по порядку (строк меньше телефонов — лишние остаются
без текста и это видно в итоге), по кругу и случайно.
"""
from __future__ import annotations

import random
import re

MAX_ROWS = 5000
MODES = ("order", "cycle", "random")
_PART = re.compile(r"\{(\d{1,2})\}")


def clean_rows(raw, limit: int = MAX_ROWS) -> list:
    """Строки без пустых; принимает текст или список строк."""
    if raw is None:
        return []
    items = raw.splitlines() if isinstance(raw, str) else [str(x) for x in raw]
    return [line.strip() for line in items if line and line.strip()][:limit]


def split_row(row: str, separator: str) -> list:
    """Строка на части по разделителю; без разделителя — одна часть."""
    if not separator:
        return [row]
    return [part.strip() for part in row.split(separator)]


def render(template: str, fields: list) -> str:
    """Шаблон «{1}@mail.ru» с частями строки; пустой шаблон — вся строка."""
    if not template:
        return " ".join(fields) if len(fields) > 1 else (fields[0] if fields else "")

    def part(match):
        n = int(match.group(1))
        return fields[n - 1] if 1 <= n <= len(fields) else ""
    return _PART.sub(part, template)


def assign(serials, rows, mode: str, rng=None) -> dict:
    """Какая строка достаётся какому телефону; None — строки не хватило."""
    if mode not in MODES:
        raise ValueError(f"режим «{mode}» неизвестен: по порядку, по кругу или случайно")
    rng = rng or random
    out = {}
    for i, serial in enumerate(serials):
        if not rows:
            out[serial] = None
        elif mode == "order":
            out[serial] = rows[i] if i < len(rows) else None
        elif mode == "cycle":
            out[serial] = rows[i % len(rows)]
        else:
            out[serial] = rng.choice(rows)
    return out
```

`backend/farm/api/bulk.py`: добавить `from .. import lines as lines_mod` к импортам и после `bulk_display` вставить:

```python
@router.post("/text_lines")
def text_lines(serials: list[str] = Body(...), lines: list[str] = Body(...),
               mode: str = Body("order"), separator: str = Body(""),
               template: str = Body(""), clear: bool = Body(False)):
    """«Каждому своё»: строка файла — на свой телефон. Телефоны без строки
    попадают в итог ошибкой «не хватило строк», а не пропадают молча."""
    rows = lines_mod.clean_rows(lines)
    if not rows:
        raise HTTPException(400, "в файле нет ни одной строки")
    targets = _online(serials)
    try:
        plan = lines_mod.assign(targets, rows, mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    texts = {s: lines_mod.render(template, lines_mod.split_row(row, separator))
             for s, row in plan.items() if row is not None}

    def send(serial):
        ACTIONS["text"](serial, {"type": "text", "value": texts[serial], "clear": clear})

    result = _each(list(texts), send, serials)
    for s in plan:
        if s not in texts:
            result["results"][s] = failure("не хватило строк в файле")
            result["failed"] += 1
    result["ok"] = result["failed"] == 0
    return result
```

(Параметр называется `lines`, а модуль импортирован как `lines_mod`, чтобы имя параметра не затеняло модуль.)

- [ ] **Step 4: Implement frontend**

`frontend/js/bulk.js`, перед `function bulkMenu()`, добавить:

```javascript
/* строки: начало */
/* «Каждому своё»: строка файла — на свой телефон. */
function bulkLinesRows(text) {
    return String(text || '').split(/\r?\n/).map(s => s.trim()).filter(Boolean).slice(0, 5000);
}

function bulkLinesPlan(names, rows, mode) {
    return names.map((name, i) => {
        let text = null;
        if (rows.length) {
            if (mode === 'cycle') text = rows[i % rows.length];
            else if (mode === 'random') text = rows[Math.floor(Math.random() * rows.length)];
            else text = i < rows.length ? rows[i] : null;
        }
        return {name, text};
    });
}
/* строки: конец */

/* Файл в UTF-8, а Excel на русском сохраняет в Windows-1251: пробуем
   строго UTF-8 и, если не вышло, читаем как 1251. */
async function bulkLinesLoad(file) {
    if (!file) return;
    const buf = await file.arrayBuffer();
    let text;
    try {
        text = new TextDecoder('utf-8', {fatal: true}).decode(buf);
    } catch (e) {
        text = new TextDecoder('windows-1251').decode(buf);
    }
    $('bulkLines').value = text.replace(/^﻿/, '');
    bulkLinesPreview();
}

function bulkLinesPreview() {
    const rows = bulkLinesRows($('bulkLines').value);
    const names = bulkTargets().map(serial => {
        const d = S.devices.find(x => x.serial === serial);
        return d ? d.name : serial;
    });
    const plan = bulkLinesPlan(names, rows, $('bulkLinesMode').value);
    const missing = plan.filter(p => p.text === null).length;
    $('bulkLinesInfo').textContent = rows.length
        ? `Строк: ${rows.length}, телефонов: ${names.length}`
            + (missing ? ` · без строки останутся ${missing}` : '')
            + ' · ' + plan.slice(0, 3).map(p => `${p.name} → ${p.text === null ? '—' : p.text}`).join('; ')
        : 'Вставьте строки или выберите файл .txt / .csv';
}

function bulkSendLines() {
    const rows = bulkLinesRows($('bulkLines').value);
    if (!rows.length) return toast('нет строк', 'bad');
    const serials = bulkTargets();
    if (!serials.length) return toast('выберите телефоны в сети', 'bad');
    return bulkRun('Каждому своё', serials, list => post('/api/bulk/text_lines', {
        serials: list, lines: rows, mode: $('bulkLinesMode').value,
        separator: $('bulkLinesSep').value, template: $('bulkLinesTpl').value,
        clear: $('bulkLinesClear').checked}));
}
```

В `bulkMenu`, в группу «Текст, группа и теги», после плитки «Ввести текст»:

```javascript
      ${tile("bulkPanel('lines')", 'keyboard', 'Каждому своё', 'строка файла — на свой телефон', 'lines')}
```

В `bulkPanel`, ключ в объекте:

```javascript
        lines: `<textarea id="bulkLines" rows="5" placeholder="по строке на телефон: логин, ссылка, текст"
              aria-label="Строки" oninput="bulkLinesPreview()"></textarea>
          <div class="bp-row">
            <input type="file" accept=".txt,.csv" aria-label="Файл" onchange="bulkLinesLoad(this.files[0])">
            <select id="bulkLinesMode" aria-label="Как раздать" onchange="bulkLinesPreview()">
              <option value="order">по порядку</option><option value="cycle">по кругу</option>
              <option value="random">случайно</option></select>
            <label><input type="checkbox" id="bulkLinesClear"> стереть поле перед вводом</label></div>
          <div class="bp-row">
            <input id="bulkLinesSep" placeholder="делить строку по (например ;)" aria-label="Разделитель">
            <input id="bulkLinesTpl" placeholder="шаблон, например {1}@mail.ru" aria-label="Шаблон">
            <button class="sm primary" onclick="bulkSendLines()">Ввести</button></div>
          <small class="dim" id="bulkLinesInfo"></small>`,
```

и после `if (kind === 'res') bulkResLoad();` добавить `if (kind === 'lines') bulkLinesPreview();`.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_lines.py tests/test_bulk_lines_js.py tests/test_bulk_resolution_js.py -q`
Expected: all PASS.

```bash
git add backend/farm/lines.py backend/farm/api/bulk.py frontend/js/bulk.js backend/tests/test_lines.py backend/tests/test_bulk_lines_js.py
git commit -m "F4: пакетный ввод «каждому своё» из файла"
```

---

### Task 4: F8 — горячие клавиши F1–F9 для фраз

**Files:**
- Modify: `frontend/js/bulk.js` (`phrasesHtml`, новый блок и обработчик)
- Test: `backend/tests/test_phrase_hotkeys_js.py`

**Interfaces:**
- Consumes: `phrases()`, `bulkAction(action, what)`.
- Produces: `phraseForHotkey(ev, list) -> string | null`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_phrase_hotkeys_js.py`:

```python
"""F1–F9 вводят быстрые фразы (bulk.js: phraseForHotkey)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "bulk.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('/* горячие клавиши фраз: начало */'), b = src.indexOf('/* горячие клавиши фраз: конец */');
assert.ok(a > 0 && b > a, 'нет маркеров блока');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src.slice(a, b) + ';this.f=phraseForHotkey', ctx);
const list = ['раз', 'два', 'три'];
const key = (k, extra) => Object.assign({key: k}, extra || {});
assert.strictEqual(ctx.f(key('F1'), list), 'раз');
assert.strictEqual(ctx.f(key('F3'), list), 'три');
assert.strictEqual(ctx.f(key('F4'), list), null);          // фразы с таким номером нет
assert.strictEqual(ctx.f(key('F10'), list), null);         // только F1–F9
assert.strictEqual(ctx.f(key('F0'), list), null);
assert.strictEqual(ctx.f(key('a'), list), null);
assert.strictEqual(ctx.f(key('F1', {ctrlKey: true}), list), null);
assert.strictEqual(ctx.f(key('F1', {shiftKey: true}), list), null);
assert.strictEqual(ctx.f(key('F1'), []), null);
"""


def test_phrase_hotkey():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_phrase_hotkeys_js.py -q`
Expected: FAIL (нет маркеров блока).

- [ ] **Step 3: Implement**

`frontend/js/bulk.js`, сразу перед `function phrases()` добавить:

```javascript
/* горячие клавиши фраз: начало */
/* F1–F9 вводят первую–девятую быструю фразу на выбранных телефонах, пока
   открыта панель «Ввести текст». С модификаторами не срабатывают: Ctrl+F5
   браузера не должен печатать фразу. */
function phraseForHotkey(ev, list) {
    if (ev.ctrlKey || ev.altKey || ev.metaKey || ev.shiftKey) return null;
    const m = /^F([1-9])$/.exec(ev.key || '');
    return m ? (list[Number(m[1]) - 1] || null) : null;
}
/* горячие клавиши фраз: конец */

document.addEventListener('keydown', ev => {
    const box = document.getElementById('bulkPhrases');
    if (!box || box.offsetParent === null) return;                 // панели с фразами не видно
    if (ev.target.closest && ev.target.closest('input, textarea, select, [contenteditable]')) return;
    const text = phraseForHotkey(ev, phrases());
    if (!text) return;
    ev.preventDefault();
    bulkAction({type: 'text', value: text}, 'Фраза');
});
```

В `phrasesHtml()` заменить подпись кнопки фразы, чтобы показывать клавишу (первые девять):

```javascript
      <button class="sm" onclick="bulkAction({type:'text',value:phrases()[${i}]},'Фраза')"
              title="${i < 9 ? `F${i + 1} — ` : ''}Ввести на всех выбранных">${i < 9 ? `<kbd>F${i + 1}</kbd> ` : ''}${esc(p)}</button>
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_phrase_hotkeys_js.py tests/test_bulk_lines_js.py tests/test_bulk_resolution_js.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/bulk.js backend/tests/test_phrase_hotkeys_js.py
git commit -m "F8: горячие клавиши F1–F9 для быстрых фраз"
```

---

### Task 5: окно «Инструменты» — общая оболочка

**Files:**
- Create: `frontend/js/tools.js`, `frontend/css/tools.css`
- Modify: `frontend/index.html` (кнопка в шапке перед кнопкой `restartAdb`, подключение css и js), `frontend/strings/ru.json`
- Test: `backend/tests/test_tools_js.py`

**Interfaces:**
- Produces (JS): `toolsRegister({id, icon, title, sub, open})`, `toolsTilesHtml(list) -> string`, `toolsOpen()`, `toolsRun(id)`, `toolsBackButton() -> string` (кнопка «← К инструментам» для нижней панели диалога каждой вкладки).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tools_js.py`:

```python
"""Окно «Инструменты»: реестр вкладок и плитки (tools.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "tools.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {
  esc: s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),
  t: k => k,
};
vm.createContext(ctx);
vm.runInContext(src + ';this.reg=toolsRegister;this.tiles=toolsTilesHtml;this.list=TOOLS;this.back=toolsBackButton', ctx);
ctx.reg({id: 'health', icon: 'sliders', title: 'Здоровье <b>', sub: 'ОЗУ и память', open() {}});
ctx.reg({id: 'backup', icon: 'download', title: 'Копия', sub: 'архив', open() {}});
assert.strictEqual(ctx.list.length, 2);
const html = ctx.tiles(ctx.list);
assert.ok(html.includes("toolsRun('health')") && html.includes("toolsRun('backup')"));
assert.ok(html.includes('Здоровье &lt;b&gt;'), 'заголовок экранируется');
assert.ok(html.includes('#i-sliders'));
assert.ok(ctx.back().includes('toolsOpen()'));
// повторная регистрация того же id заменяет вкладку, а не дублирует
ctx.reg({id: 'health', icon: 'x', title: 'Новое', sub: '', open() {}});
assert.strictEqual(ctx.list.length, 2);
assert.strictEqual(ctx.list.find(x => x.id === 'health').title, 'Новое');
"""


def test_tools_registry_and_tiles():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tools_js.py -q`
Expected: FAIL (`tools.js` не существует).

- [ ] **Step 3: Implement**

Create `frontend/js/tools.js`:

```javascript
'use strict';

/* «Инструменты фермы»: окно для вещей, которые относятся ко всей ферме, а не к
   одному телефону или сценарию (здоровье, уведомления, резервная копия, API,
   черновик по описанию). Вкладка регистрирует себя сама через toolsRegister,
   поэтому новый инструмент — отдельный файл и одна строка в index.html. */

const TOOLS = [];

function toolsRegister(tool) {
    const at = TOOLS.findIndex(x => x.id === tool.id);
    if (at >= 0) TOOLS[at] = tool;
    else TOOLS.push(tool);
}

function toolsTilesHtml(list) {
    return list.map(tool => `<button onclick="toolsRun('${esc(tool.id)}')">
        <svg class="ic" aria-hidden="true"><use href="#i-${esc(tool.icon)}"/></svg>
        <b>${esc(tool.title)}</b><span>${esc(tool.sub)}</span></button>`).join('');
}

function toolsBackButton() {
    return `<button onclick="toolsOpen()">${esc(t('tools.nazad'))}</button>`;
}

function toolsOpen() {
    $('mTitle').textContent = t('tools.zagolovok');
    $('mBody').innerHTML = `<div class="bulk-grid">${toolsTilesHtml(TOOLS)}</div>`;
    $('mActs').innerHTML = `<span class="sp"></span><button onclick="closeModal()">${esc(t('tools.zakryt'))}</button>`;
    modalSheet('wide');
    openModal();
}

function toolsRun(id) {
    const tool = TOOLS.find(x => x.id === id);
    if (tool) tool.open();
}
```

Create `frontend/css/tools.css`:

```css
/* Окно «Инструменты фермы» (tools.js). Плитки берут вид у .bulk-grid. */
.tool-table {
    width: 100%;
    border-collapse: collapse;
}

.tool-table th,
.tool-table td {
    padding: var(--s1) var(--s2);
    text-align: left;
    border-bottom: 1px solid var(--line-soft);
}

.tool-table td.bad {
    color: var(--bad, #c0392b);
    font-weight: 600;
}

.tool-note {
    color: var(--dim);
    margin: var(--s2) 0;
}

.tool-warn {
    color: var(--bad, #c0392b);
    margin: var(--s2) 0;
}
```

`frontend/index.html`:
1. В `<head>` после `css/vlm.css`: `<link rel="stylesheet" href="css/tools.css">`.
2. Непосредственно перед кнопкой `restartAdb` (около строки 153) добавить:

```html
    <button class="sm icon" onclick="toolsOpen()" aria-label="Инструменты фермы"
            title="Здоровье телефонов, уведомления, резервная копия, API" data-t-title="tools.podskazka" data-t-aria-label="tools.zagolovok">
        <svg class="ic" aria-hidden="true">
            <use href="#i-sliders"/>
        </svg>
    </button>
```
3. Перед `<script src="js/app.js">` (и после `js/files.js`/`notify.js`, до `app.js`) добавить `<script src="js/tools.js"></script>`.

`frontend/strings/ru.json` (в алфавитном порядке):

```json
"tools.nazad": "← К инструментам",
"tools.podskazka": "Здоровье телефонов, уведомления, резервная копия, API",
"tools.zagolovok": "Инструменты фермы",
"tools.zakryt": "Закрыть",
```

- [ ] **Step 4: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_tools_js.py tests/test_strings.py -q`
Expected: all PASS.

```bash
git add frontend/js/tools.js frontend/css/tools.css frontend/index.html frontend/strings/ru.json backend/tests/test_tools_js.py
git commit -m "Инструменты фермы: окно с реестром вкладок и кнопка в шапке"
```

---

### Task 6: F3 — монитор здоровья (RAM, ROM, CPU)

**Files:**
- Create: `backend/farm/health.py`, `frontend/js/tool-health.js`
- Modify: `backend/farm/adb.py` (функция `health_snapshot`), `backend/farm/config.py` (пороги), `backend/farm/devices/registry.py` (поля `ram_free`, `rom_used`, `cpu`, чтение в `_read_health`, тревоги в `warnings`, очистка в `forget_health`, словарь `_cpu_prev`), `frontend/index.html` (подключение скрипта)
- Test: `backend/tests/test_health.py`, `backend/tests/test_tool_health_js.py`

**Interfaces:**
- Produces:
  - `health.HEALTH_CMD: str` — одна команда, один вызов adb
  - `health.split_sections(out) -> dict` — `{"mem": str, "df": str, "stat": str}`
  - `health.parse_meminfo(text) -> dict | None`, `health.ram_free_pct(info) -> int | None`
  - `health.parse_df(text) -> int | None` — процент занятого `/data`
  - `health.parse_cpu_stat(text) -> tuple[int, int] | None` — `(busy, total)`
  - `health.cpu_percent(prev, cur) -> int | None`
  - `health.read(out, prev) -> tuple[dict, tuple | None]` — `({"ram_free", "rom_used", "cpu"}, новый_образец)`
  - `Device.ram_free: int | None`, `Device.rom_used: int | None`, `Device.cpu: int | None` (попадают в `/api/devices`)
  - JS: `healthRows(devices) -> [{name, battery, temp, rom, ram, cpu, bad: [...]}]`, `HEALTH_LIMITS`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_health.py`:

```python
"""Здоровье телефона: разбор /proc/meminfo, df, /proc/stat и тревоги реестра."""
from farm import config, health
from farm.devices import registry

MEM = ("MemTotal:        3815884 kB\nMemFree:          123456 kB\n"
       "MemAvailable:    1907942 kB\n")
DF = ("Filesystem       Size  Used Avail Use% Mounted on\n"
      "/dev/block/dm-9  118G   60G   58G  51% /data\n")
STAT1 = "cpu  1000 0 500 8000 100 0 0 0 0 0\n"
STAT2 = "cpu  1300 0 700 8400 100 0 0 0 0 0\n"
OUT = f"{MEM}#df\n{DF}#stat\n{STAT1}"


def test_split_sections():
    got = health.split_sections(OUT)
    assert got["mem"].startswith("MemTotal") and "/data" in got["df"] and got["stat"].startswith("cpu")


def test_split_sections_missing_parts():
    got = health.split_sections(MEM)
    assert got["df"] == "" and got["stat"] == ""


def test_meminfo_and_free_percent():
    info = health.parse_meminfo(MEM)
    assert info == {"total_kb": 3815884, "available_kb": 1907942}
    assert health.ram_free_pct(info) == 50
    assert health.parse_meminfo("") is None
    assert health.ram_free_pct(None) is None


def test_meminfo_without_available_uses_free_plus_cache():
    text = "MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 50 kB\nCached: 150 kB\n"
    assert health.ram_free_pct(health.parse_meminfo(text)) == 30


def test_df_used_percent():
    assert health.parse_df(DF) == 51
    assert health.parse_df("") is None
    assert health.parse_df("/dev/x 1G 1G 0 100% /data\n") == 100


def test_cpu_stat_and_percent():
    prev, cur = health.parse_cpu_stat(STAT1), health.parse_cpu_stat(STAT2)
    assert prev == (1500, 9600) and cur == (2000, 10500)
    assert health.cpu_percent(prev, cur) == 56          # 500 занятых из 900
    assert health.cpu_percent(None, cur) is None
    assert health.cpu_percent(cur, cur) is None          # нулевой промежуток
    assert health.parse_cpu_stat("garbage") is None


def test_read_returns_metrics_and_next_sample():
    first, sample = health.read(OUT, None)
    assert first == {"ram_free": 50, "rom_used": 51, "cpu": None}
    out2 = f"{MEM}#df\n{DF}#stat\n{STAT2}"
    second, _ = health.read(out2, sample)
    assert second["cpu"] == 56


def _device(**kw):
    d = registry.Device(serial="S1")
    d.state = "device"
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_warnings_for_full_storage_and_low_ram():
    d = _device(rom_used=95, ram_free=5)
    text = " | ".join(d.warnings())
    assert "память почти заполнена" in text and "95%" in text
    assert "мало оперативной памяти" in text


def test_no_warnings_when_healthy_or_unknown():
    assert _device(rom_used=60, ram_free=40).warnings() == []
    assert _device().warnings() == []


def test_thresholds_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "ROM_ALERT_PCT", 50)
    assert any("заполнена" in w for w in _device(rom_used=51).warnings())


def test_forget_health_clears_new_fields():
    d = _device(rom_used=80, ram_free=10, cpu=30)
    d.forget_health()
    assert d.rom_used is None and d.ram_free is None and d.cpu is None


def test_to_dict_exposes_new_fields():
    d = _device(rom_used=80, ram_free=10, cpu=30).to_dict()
    assert (d["rom_used"], d["ram_free"], d["cpu"]) == (80, 10, 30)
```

Create `backend/tests/test_tool_health_js.py`:

```python
"""Таблица здоровья: строки, подсветка, порядок (tool-health.js)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "tool-health.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {toolsRegister() {}, esc: s => String(s), t: k => k};
vm.createContext(ctx);
vm.runInContext(src + ';this.rows=healthRows', ctx);
const rows = ctx.rows([
  {online: true, name: 'Б', battery: 80, temperature: 30, rom_used: 50, ram_free: 40, cpu: 10},
  {online: true, name: 'А', battery: 10, temperature: 45, rom_used: 95, ram_free: 5, cpu: 90},
  {online: false, name: 'Офлайн', battery: 1},
  {online: true, name: 'В', battery: null, temperature: null, rom_used: null, ram_free: null, cpu: null},
]);
assert.deepStrictEqual(rows.map(r => r.name), ['А', 'В', 'Б']);      // больше проблем — выше; офлайн не берём
assert.deepStrictEqual([...rows[0].bad].sort(), ['battery', 'ram', 'rom', 'temp']);
assert.deepStrictEqual(rows[1].bad, []);                              // нет данных — не тревога
"""


def test_health_rows():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_health.py tests/test_tool_health_js.py -q`
Expected: FAIL `ImportError: cannot import name 'health' from 'farm'`.

- [ ] **Step 3: Implement backend**

Create `backend/farm/health.py`:

```python
"""Здоровье телефона: память, место и загрузка процессора.

Чистый разбор вывода adb, без самого adb. Всё читается ОДНОЙ командой за
проход опроса: сорок телефонов раз в 20 секунд не должны получать по четыре
вызова. Загрузка CPU считается между двумя проходами (по /proc/stat), поэтому
ждать полсекунды на телефоне не нужно.
"""
from __future__ import annotations

import re

HEALTH_CMD = "head -n 5 /proc/meminfo; echo '#df'; df /data; echo '#stat'; head -n 1 /proc/stat"

_MEM = re.compile(r"^(\w+):\s+(\d+)\s*kB", re.M)
_PCT = re.compile(r"(\d{1,3})%")


def split_sections(out) -> dict:
    """Вывод HEALTH_CMD на три части; чего нет — пустая строка."""
    text = out or ""
    mem, _, rest = text.partition("#df")
    df, _, stat = rest.partition("#stat")
    return {"mem": mem.strip(), "df": df.strip(), "stat": stat.strip()}


def parse_meminfo(text):
    fields = {k: int(v) for k, v in _MEM.findall(text or "")}
    if not fields.get("MemTotal"):
        return None
    available = fields.get("MemAvailable")
    if available is None:                     # старые Android: свободно + буферы + кэш
        available = fields.get("MemFree", 0) + fields.get("Buffers", 0) + fields.get("Cached", 0)
    return {"total_kb": fields["MemTotal"], "available_kb": available}


def ram_free_pct(info):
    if not info or not info["total_kb"]:
        return None
    return int(round(100 * info["available_kb"] / info["total_kb"]))


def parse_df(text):
    """Процент занятого места на /data из вывода df."""
    for line in reversed((text or "").splitlines()):
        match = _PCT.search(line)
        if match:
            return int(match.group(1))
    return None


def parse_cpu_stat(text):
    """(занято, всего) из строки «cpu  user nice system idle iowait …»."""
    parts = (text or "").split()
    if len(parts) < 5 or parts[0] != "cpu":
        return None
    try:
        nums = [int(p) for p in parts[1:]]
    except ValueError:
        return None
    total = sum(nums[:8])
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
    return total - idle, total


def cpu_percent(prev, cur):
    """Загрузка между двумя образцами; нет прошлого или нулевой промежуток — None."""
    if not prev or not cur or cur[1] <= prev[1]:
        return None
    return int(round(100 * (cur[0] - prev[0]) / (cur[1] - prev[1])))


def read(out, prev):
    """Метрики из вывода HEALTH_CMD и новый образец CPU для следующего прохода."""
    parts = split_sections(out)
    sample = parse_cpu_stat(parts["stat"])
    metrics = {"ram_free": ram_free_pct(parse_meminfo(parts["mem"])),
               "rom_used": parse_df(parts["df"]),
               "cpu": cpu_percent(prev, sample)}
    return metrics, sample
```

`backend/farm/config.py`, после `BATTERY_HIGH`:

```python
# Тревоги памяти телефона (farm/health.py): место занято, оперативки почти нет.
ROM_ALERT_PCT = int(os.getenv("FARM_ROM_ALERT_PCT", "92"))
RAM_ALERT_FREE_PCT = int(os.getenv("FARM_RAM_ALERT_FREE_PCT", "8"))
```

`backend/farm/adb.py`: в конец файла добавить

```python
def health_snapshot(serial: str) -> str:
    """Сырой вывод health.HEALTH_CMD — разбирает farm/health.py."""
    from . import health   # health чистый; импорт по месту, чтобы adb оставался листом
    return shell(serial, health.HEALTH_CMD, timeout=10)
```

`backend/farm/devices/registry.py`:
1. Рядом с `temperature: float | None = None` (строка ~50) добавить поля:

```python
    ram_free: int | None = None    # % оперативной памяти свободно
    rom_used: int | None = None    # % места на /data занято
    cpu: int | None = None         # % загрузки процессора между опросами
```
2. В `forget_health` добавить `self.ram_free = self.rom_used = self.cpu = None`.
3. В `warnings()` внутри блока `if self.online:` после блока заряда добавить:

```python
            if self.rom_used is not None and self.rom_used >= config.ROM_ALERT_PCT:
                w.append(f"память почти заполнена: занято {self.rom_used}%")
            if self.ram_free is not None and self.ram_free <= config.RAM_ALERT_FREE_PCT:
                w.append(f"мало оперативной памяти: свободно {self.ram_free}%")
```
4. В `to_dict`, в блоке `if not self.online:` после `d["temperature"] = None` добавить `d["ram_free"] = d["rom_used"] = d["cpu"] = None`.
5. В `Registry.__init__` добавить `self._cpu_prev: dict[str, tuple] = {}`; импорт `from .. import health` рядом с остальными.
6. В `_read_health` после строки `d.charging = b.get("plugged", "")` добавить:

```python
            try:
                metrics, sample = health.read(adb.health_snapshot(d.serial),
                                              self._cpu_prev.get(d.serial))
                d.ram_free, d.rom_used, d.cpu = (metrics["ram_free"], metrics["rom_used"], metrics["cpu"])
                if sample:
                    self._cpu_prev[d.serial] = sample
            except Exception:  # noqa: BLE001 — память не повод помечать телефон ошибкой
                d.ram_free = d.rom_used = d.cpu = None
```

- [ ] **Step 4: Implement frontend**

Create `frontend/js/tool-health.js`:

```javascript
'use strict';

/* Инструмент «Здоровье телефонов»: заряд, температура, место, оперативная
   память и загрузка процессора по всей ферме. Данные уже приходят с опросом
   /api/devices, отдельного запроса нет. Пороги те же, что на сервере
   (config.py: TEMP_ALERT_C, BATTERY_LOW, ROM_ALERT_PCT, RAM_ALERT_FREE_PCT). */

const HEALTH_LIMITS = {temp: 42, battery: 20, rom: 92, ramFree: 8};

function healthRows(devices) {
    return devices.filter(d => d.online).map(d => {
        const bad = [];
        if (d.temperature != null && d.temperature >= HEALTH_LIMITS.temp) bad.push('temp');
        if (d.battery != null && d.battery <= HEALTH_LIMITS.battery) bad.push('battery');
        if (d.rom_used != null && d.rom_used >= HEALTH_LIMITS.rom) bad.push('rom');
        if (d.ram_free != null && d.ram_free <= HEALTH_LIMITS.ramFree) bad.push('ram');
        return {name: d.name, battery: d.battery, temp: d.temperature,
                rom: d.rom_used, ram: d.ram_free, cpu: d.cpu, bad};
    }).sort((a, b) => b.bad.length - a.bad.length || String(a.name).localeCompare(String(b.name), 'ru'));
}

function healthOpen() {
    const rows = healthRows(S.devices || []);
    const cell = (row, key, value, suffix) =>
        `<td${row.bad.includes(key) ? ' class="bad"' : ''}>${value == null ? '—' : esc(value) + suffix}</td>`;
    $('mTitle').textContent = 'Здоровье телефонов';
    $('mBody').innerHTML = rows.length ? `
      <p class="tool-note">Красным — то, что пора починить: заряд, перегрев, мало места или памяти. Обновляется само.</p>
      <table class="tool-table">
        <thead><tr><th>Телефон</th><th>Заряд</th><th>Температура</th><th>Место занято</th><th>ОЗУ свободно</th><th>Процессор</th></tr></thead>
        <tbody>${rows.map(r => `<tr><td>${esc(r.name)}</td>
          ${cell(r, 'battery', r.battery, '%')}${cell(r, 'temp', r.temp, '°C')}
          ${cell(r, 'rom', r.rom, '%')}${cell(r, 'ram', r.ram, '%')}${cell(r, 'cpu', r.cpu, '%')}</tr>`).join('')}</tbody>
      </table>`
        : '<p class="tool-note">Нет телефонов в сети.</p>';
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'health', icon: 'sliders', title: 'Здоровье телефонов',
               sub: 'заряд, нагрев, память, процессор', open: healthOpen});
```

`frontend/index.html`: после `<script src="js/tools.js">` добавить `<script src="js/tool-health.js"></script>`.

- [ ] **Step 5: Run the whole suite (registry tests may assert exact dict keys) and commit**

Run: `cd backend && python -m pytest -q`
Expected: all PASS. Если упал существующий тест реестра, сверяющий точный набор ключей `to_dict`, — добавить в ожидаемый набор `ram_free`, `rom_used`, `cpu` (это ожидаемое расширение, не поломка).

```bash
git add backend/farm/health.py backend/farm/adb.py backend/farm/config.py backend/farm/devices/registry.py frontend/js/tool-health.js frontend/index.html backend/tests/test_health.py backend/tests/test_tool_health_js.py
git commit -m "F3: монитор здоровья — ОЗУ, место, процессор и тревоги в «Требуют внимания»"
```

---

### Task 7: F2 — резервная копия фермы

**Files:**
- Create: `backend/farm/backup.py`, `backend/farm/api/backup.py`, `frontend/js/tool-backup.js`
- Modify: `backend/farm/api/__init__.py` (подключить роутер), `frontend/index.html` (скрипт)
- Test: `backend/tests/test_backup.py`

**Interfaces:**
- Consumes: `config.DATA_DIR`, `config.DATA_FILES`, `config.SCENARIOS_DIR`.
- Produces:
  - `backup.ADB_DIR: Path` (по умолчанию `~/.android`), `backup.MAX_TOTAL = 64 * 1024 * 1024`, `backup.MAX_FILES = 2000`
  - `backup.build(include_adb_key: bool = False) -> bytes`
  - `backup.inspect(blob: bytes) -> dict` — `{"files": [имена], "has_adb_key": bool, "bytes": int}`; `ValueError` на негодном архиве
  - `backup.restore(blob: bytes, adb_key: bool = False) -> dict` — `{"restored": [...], "skipped": [{"name", "why"}], "saved_previous_to": str | None}`
  - API: `POST /api/backup/export` тело `{"adb_key": bool}` → zip; `POST /api/backup/inspect` (тело — сам zip); `POST /api/backup/restore?adb_key=0|1` (тело — zip)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backup.py`:

```python
"""Резервная копия: что кладётся, что нет, безопасное восстановление."""
import asyncio
import io
import zipfile

import pytest
from fastapi import HTTPException

from farm import backup, config
from farm.api import backup as api_backup


@pytest.fixture
def farm(tmp_path, monkeypatch):
    data, sc, adb = tmp_path / "data", tmp_path / "scenarios", tmp_path / ".android"
    for d in (data, sc, adb):
        d.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "SCENARIOS_DIR", sc)
    monkeypatch.setattr(backup, "ADB_DIR", adb)
    (data / "accounts.json").write_text('{"a": 1}', "utf-8")
    (data / "groups.json").write_text('{"g": 1}', "utf-8")
    (data / "vlm.json").write_text('{"key": "SECRET"}', "utf-8")          # ключ нейросети в копию не идёт
    (data / "artifacts").mkdir()
    (data / "artifacts" / "big.jpg").write_bytes(b"x" * 100)
    (sc / "vk_like.py").write_text("RECORDED = True\n", "utf-8")
    (sc / "_template.py").write_text("x = 1\n", "utf-8")
    (sc / "vk_like_assets").mkdir()
    (sc / "vk_like_assets" / "recipe.json").write_text("{}", "utf-8")
    (adb / "adbkey").write_text("PRIVATE", "utf-8")
    (adb / "adbkey.pub").write_text("PUBLIC", "utf-8")
    return tmp_path


def names(blob):
    return sorted(zipfile.ZipFile(io.BytesIO(blob)).namelist())


def make_zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_build_includes_whitelisted_files_only(farm):
    got = names(backup.build())
    assert "data/accounts.json" in got and "data/groups.json" in got
    assert "scenarios/vk_like.py" in got and "scenarios/vk_like_assets/recipe.json" in got
    assert not any("vlm" in n or "artifacts" in n or "_template" in n for n in got)
    assert not any(n.startswith("adb/") for n in got)


def test_adb_key_only_when_asked(farm):
    assert "adb/adbkey" in names(backup.build(include_adb_key=True))


def test_inspect_lists_files_and_key_flag(farm):
    info = backup.inspect(backup.build(include_adb_key=True))
    assert info["has_adb_key"] is True and "data/accounts.json" in info["files"]
    assert backup.inspect(backup.build())["has_adb_key"] is False


def test_inspect_rejects_non_zip():
    with pytest.raises(ValueError):
        backup.inspect(b"not a zip")


def test_restore_round_trip_and_previous_saved(farm):
    blob = backup.build()
    (config.DATA_DIR / "accounts.json").write_text('{"changed": true}', "utf-8")
    report = backup.restore(blob)
    assert (config.DATA_DIR / "accounts.json").read_text("utf-8") == '{"a": 1}'
    assert "data/accounts.json" in report["restored"]
    saved = report["saved_previous_to"]
    assert saved and (config.DATA_DIR / ".restore-backup").exists()
    assert any(p.read_text("utf-8") == '{"changed": true}'
               for p in (config.DATA_DIR / ".restore-backup").rglob("accounts.json"))


@pytest.mark.parametrize("name", [
    "../evil.txt", "data/../evil.txt", "/etc/passwd", "data/vlm.json", "data/artifacts/x.jpg",
    "scenarios/../x.py", "scenarios/x.sh", "scenarios/a/b.py", "adb/other", "random.txt",
    "data\\accounts.json", "scenarios/gallery/tiktok_feed.py",
])
def test_restore_skips_unsafe_or_unknown_names(farm, name):
    report = backup.restore(make_zip({name: "x"}))
    assert report["restored"] == []
    assert report["skipped"][0]["name"] == name
    assert not (farm / "evil.txt").exists()


def test_restore_adb_key_only_when_allowed(farm):
    blob = make_zip({"adb/adbkey": "NEWKEY"})
    assert backup.restore(blob, adb_key=False)["restored"] == []
    assert (backup.ADB_DIR / "adbkey").read_text("utf-8") == "PRIVATE"
    assert backup.restore(blob, adb_key=True)["restored"] == ["adb/adbkey"]
    assert (backup.ADB_DIR / "adbkey").read_text("utf-8") == "NEWKEY"


def test_restore_enforces_total_size(farm, monkeypatch):
    monkeypatch.setattr(backup, "MAX_TOTAL", 10)
    with pytest.raises(ValueError):
        backup.restore(make_zip({"data/accounts.json": "x" * 50}))


def test_restore_enforces_file_count(farm, monkeypatch):
    monkeypatch.setattr(backup, "MAX_FILES", 2)
    with pytest.raises(ValueError):
        backup.restore(make_zip({f"data/accounts{i}.json": "x" for i in range(5)}))


class Req:
    def __init__(self, data):
        self.headers = {"content-length": str(len(data))}
        self._data = data

    async def stream(self):
        yield self._data


def test_api_export_returns_zip_response(farm):
    resp = api_backup.export_backup({"adb_key": False})
    assert resp.media_type == "application/zip"
    assert "farm-backup-" in resp.headers["content-disposition"]
    assert "data/accounts.json" in names(resp.body)


def test_api_inspect_and_restore(farm):
    blob = backup.build()
    info = asyncio.run(api_backup.inspect_backup(Req(blob)))
    assert "data/accounts.json" in info["files"]
    out = asyncio.run(api_backup.restore_backup(Req(blob), adb_key=0))
    assert "data/accounts.json" in out["restored"]


def test_api_rejects_bad_archive_with_400(farm):
    with pytest.raises(HTTPException) as e:
        asyncio.run(api_backup.inspect_backup(Req(b"junk")))
    assert e.value.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_backup.py -q`
Expected: FAIL `ImportError: cannot import name 'backup' from 'farm'`.

- [ ] **Step 3: Implement backend**

Create `backend/farm/backup.py`:

```python
"""Резервная копия фермы: архив с данными, записанными сценариями и (по желанию) ключом adb.

Зачем. Сломался компьютер — и сорок телефонов надо авторизовать заново, а
аккаунты, группы и расписание вводить с нуля. С копией ферма встаёт на новом
компьютере за минуту. Ключ adb кладётся ТОЛЬКО по явной галке: с ним любой
получает доступ ко всем телефонам.

Восстановление не доверяет архиву: имена в нём не превращаются в пути, а
сверяются с белым списком (zip-slip невозможен — путь строим сами), размер и
число файлов ограничены, а текущие файлы перед заменой уезжают в
data/.restore-backup/.
"""
from __future__ import annotations

import io
import os
import re
import time
import zipfile
from pathlib import Path

from . import config

ADB_DIR = Path.home() / ".android"
ADB_KEYS = ("adbkey", "adbkey.pub")
EXTRA_DATA = ("apks.json", "budget.json")
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 2000
_PY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*\.py$")
_ASSET_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*_assets$")
_ASSET_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


def _data_names():
    return tuple(config.DATA_FILES) + EXTRA_DATA


def _target(name: str):
    """Куда писать файл из архива или None, если имя не наше. Путь строится
    из проверенных кусков, а не берётся из архива."""
    if "\\" in name or name.startswith("/") or ".." in name.split("/"):
        return None
    parts = name.split("/")
    if parts[0] == "data" and len(parts) == 2 and parts[1] in _data_names():
        return Path(config.DATA_DIR) / parts[1]
    if parts[0] == "scenarios":
        if len(parts) == 2 and _PY.match(parts[1]) and not parts[1].startswith("_"):
            return Path(config.SCENARIOS_DIR) / parts[1]
        if len(parts) == 3 and _ASSET_DIR.match(parts[1]) and _ASSET_FILE.match(parts[2]):
            return Path(config.SCENARIOS_DIR) / parts[1] / parts[2]
    if parts[0] == "adb" and len(parts) == 2 and parts[1] in ADB_KEYS:
        return Path(ADB_DIR) / parts[1]
    return None


def build(include_adb_key: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in _data_names():
            path = Path(config.DATA_DIR) / name
            if path.is_file():
                z.write(path, f"data/{name}")
        sc = Path(config.SCENARIOS_DIR)
        for path in sorted(sc.glob("*.py")):
            if not path.name.startswith("_"):
                z.write(path, f"scenarios/{path.name}")
        for folder in sorted(sc.glob("*_assets")):
            if folder.is_dir():
                for path in sorted(folder.iterdir()):
                    if path.is_file():
                        z.write(path, f"scenarios/{folder.name}/{path.name}")
        if include_adb_key:
            for name in ADB_KEYS:
                path = Path(ADB_DIR) / name
                if path.is_file():
                    z.write(path, f"adb/{name}")
    return buf.getvalue()


def _open(blob: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ValueError("это не архив резервной копии фермы")
    infos = z.infolist()
    if len(infos) > MAX_FILES:
        raise ValueError(f"в архиве слишком много файлов ({len(infos)})")
    if sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ValueError("архив слишком большой после распаковки")
    return z


def inspect(blob: bytes) -> dict:
    z = _open(blob)
    files = [i.filename for i in z.infolist() if not i.is_dir()]
    return {"files": files, "has_adb_key": any(f.startswith("adb/") for f in files),
            "bytes": len(blob)}


def restore(blob: bytes, adb_key: bool = False) -> dict:
    z = _open(blob)
    restored, skipped = [], []
    saved_root = Path(config.DATA_DIR) / ".restore-backup" / time.strftime("%Y%m%d-%H%M%S")
    saved_any = False
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename
        target = _target(name)
        if target is None:
            skipped.append({"name": name, "why": "имя не входит в состав копии"})
            continue
        if name.startswith("adb/") and not adb_key:
            skipped.append({"name": name, "why": "ключ adb не разрешён галкой"})
            continue
        data = z.read(info)
        if target.exists():
            keep = saved_root / name
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(target.read_bytes())
            saved_any = True
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        if name.startswith("adb/") and name.endswith("adbkey"):
            os.chmod(tmp, 0o600)          # приватный ключ не должен читаться чужими
        os.replace(tmp, target)
        restored.append(name)
    return {"restored": restored, "skipped": skipped,
            "saved_previous_to": str(saved_root) if saved_any else None}
```

Create `backend/farm/api/backup.py`:

```python
"""Резервная копия фермы: выгрузка, просмотр и восстановление архива."""
from __future__ import annotations

import time

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response

from .. import backup

router = APIRouter(prefix="/api/backup")


async def _read(request: Request) -> bytes:
    """Тело запроса целиком, но не больше предела: архив из чужого источника."""
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > backup.MAX_TOTAL:
            raise HTTPException(413, "файл слишком большой")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/export")
def export_backup(payload: dict = Body(default=None)):
    # POST, а не GET: в архиве может лежать приватный ключ adb, а меняющие
    # запросы сервер принимает только со своей страницы (security.py).
    blob = backup.build(bool((payload or {}).get("adb_key")))
    name = time.strftime("farm-backup-%Y%m%d-%H%M.zip")
    return Response(blob, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/inspect")
async def inspect_backup(request: Request):
    try:
        return backup.inspect(await _read(request))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/restore")
async def restore_backup(request: Request, adb_key: int = Query(0)):
    try:
        return backup.restore(await _read(request), adb_key=bool(adb_key))
    except ValueError as e:
        raise HTTPException(400, str(e))
```

`backend/farm/api/__init__.py`: добавить `backup` в кортеж импортов и `router.include_router(backup.router)`.

- [ ] **Step 4: Implement frontend**

Create `frontend/js/tool-backup.js`:

```javascript
'use strict';

/* Инструмент «Резервная копия»: один архив с аккаунтами, группами,
   расписанием и записанными сценариями. Ключ adb кладётся только по галке. */

async function backupDownload() {
    const withKey = $('backupKey').checked;
    let res;
    try {
        res = await fetch('/api/backup/export', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({adb_key: withKey})});
    } catch (e) {
        return toast('нет связи с фермой', 'bad');
    }
    if (!res.ok) return toast('не удалось собрать копию', 'bad');
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = (res.headers.get('content-disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'farm-backup.zip';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
}

let BACKUP_FILE = null;

async function backupPick(file) {
    BACKUP_FILE = file || null;
    const box = $('backupInfo');
    if (!file) { box.textContent = ''; return; }
    try {
        const info = await api('/api/backup/inspect', {method: 'POST', body: file});
        box.textContent = `В архиве файлов: ${info.files.length}`
            + (info.has_adb_key ? ' · есть ключ adb' : '');
        $('backupRestoreBtn').disabled = false;
    } catch (e) {
        box.textContent = e.message;
        $('backupRestoreBtn').disabled = true;
    }
}

async function backupRestore(ev) {
    if (!BACKUP_FILE) return;
    if (!armConfirm(ev.currentTarget, 'Заменить текущие данные фермы данными из архива?')) return;
    try {
        const res = await api('/api/backup/restore?adb_key=' + ($('backupRestoreKey').checked ? 1 : 0),
                              {method: 'POST', body: BACKUP_FILE});
        toast(`Восстановлено: ${res.restored.length}`
            + (res.skipped.length ? `, пропущено: ${res.skipped.length}` : '')
            + (res.saved_previous_to ? '. Прежние файлы сохранены в data/.restore-backup' : ''), 'ok');
    } catch (e) {
        toast(e.message, 'bad');
    }
}

function backupOpen() {
    $('mTitle').textContent = 'Резервная копия';
    $('mBody').innerHTML = `
      <p class="tool-note">Сохраняет аккаунты, группы, теги, расписание, имена телефонов и записанные сценарии.
        Если ферма переедет на другой компьютер, всё вернётся из этого файла.</p>
      <label><input type="checkbox" id="backupKey"> положить ключ adb (телефоны не придётся авторизовать заново)</label>
      <p class="tool-warn">Ключ и пароли аккаунтов — секреты. Не отправляйте архив никому и не храните в общей папке.</p>
      <div class="bp-row"><button class="sm primary" onclick="backupDownload()">Скачать копию</button></div>
      <hr>
      <p class="tool-note">Восстановить из файла:</p>
      <div class="bp-row"><input type="file" accept=".zip" onchange="backupPick(this.files[0])" aria-label="Архив">
        <label><input type="checkbox" id="backupRestoreKey"> вернуть и ключ adb</label>
        <button class="sm danger" id="backupRestoreBtn" disabled onclick="backupRestore(event)"><span>Восстановить</span></button></div>
      <small class="dim" id="backupInfo"></small>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'backup', icon: 'upload', title: 'Резервная копия',
               sub: 'аккаунты, расписание, сценарии — одним файлом', open: backupOpen});
```

`frontend/index.html`: после `tool-health.js` добавить `<script src="js/tool-backup.js"></script>`.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_backup.py tests/test_tools_js.py -q`
Expected: all PASS.

```bash
git add backend/farm/backup.py backend/farm/api/backup.py backend/farm/api/__init__.py frontend/js/tool-backup.js frontend/index.html backend/tests/test_backup.py
git commit -m "F2: резервная копия фермы и безопасное восстановление"
```

---

### Task 8: F5 — монитор уведомлений

**Files:**
- Create: `backend/farm/notifications.py`, `backend/farm/api/notifications.py`, `frontend/js/tool-notify.js`
- Modify: `backend/farm/config.py` (`NOTIFY_WATCH_FILE`), `backend/farm/api/__init__.py`, `frontend/index.html`
- Test: `backend/tests/test_notifications.py`, `backend/tests/test_tool_notify_js.py`

**Interfaces:**
- Produces:
  - `notifications.Note` (`pkg: str, title: str, text: str`), `notifications.parse(out: str) -> list[Note]`
  - `notifications.is_secret(pkg: str) -> bool`
  - `notifications.watched() -> list[str]`, `notifications.set_watched(pkgs: list[str]) -> list[str]` (файл `config.NOTIFY_WATCH_FILE`)
  - `notifications.scan_phone(serial, packages, show_text) -> dict` — `{"count": n, "items": [{"pkg", "title", "text"}]}`
  - API: `GET /api/notifications/watch`, `PUT /api/notifications/watch` (тело `{"packages": [...]}`), `GET /api/notifications?packages=a,b&text=0|1`
  - JS: `notifSummary(results, packages) -> [{pkg, phones, total}]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_notifications.py`:

```python
"""Монитор уведомлений: разбор dumpsys, секретные приложения, список слежения."""
import pytest

from farm import config, notifications
from farm.api import notifications as api_notes

DUMP = """\
  Notification List:
    NotificationRecord(0x0a1b2c3d: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=3 key=0|com.whatsapp|1|null|10123: Notification(channel=msg pri=0 contentView=null vibrate=null sound=null defaults=0x0 flags=0x18 color=0x00000000 category=msg vis=PRIVATE))
      uid=10123 userId=0
      extras={
        android.title=String (Иван)
        android.text=String (Привет, как дела?)
        android.subText=null
      }
    NotificationRecord(0x0e1f2a3b: pkg=com.android.systemui user=UserHandle{0} id=7 tag=null importance=2 key=0|com.android.systemui|7|null|10010: Notification(channel=ALR pri=0 contentView=null vibrate=null sound=null defaults=0x0 flags=0x2 color=0x00000000 vis=PUBLIC))
      extras={
        android.title=String (USB debugging connected)
        android.text=String (Tap to disable)
      }
    NotificationRecord(0x0f2a3b4c: pkg=ru.sberbankmobile user=UserHandle{0} id=3 tag=null importance=3 key=0|ru.sberbankmobile|3|null|10200: Notification(channel=ops pri=0 flags=0x10 vis=PRIVATE))
      extras={
        android.title=String (Сбер)
        android.text=SpannableString (Ваш код 123456)
      }
    NotificationRecord(0x0a0b0c0d: pkg=com.whatsapp user=UserHandle{0} id=2 tag=null importance=3 key=0|com.whatsapp|2|null|10123: Notification(channel=msg flags=0x10))
      extras={
        android.title=String (Мария)
        android.text=null
      }
"""


def test_parse_reads_pkg_title_text_and_drops_ongoing():
    notes = notifications.parse(DUMP)
    assert [(n.pkg, n.title, n.text) for n in notes] == [
        ("com.whatsapp", "Иван", "Привет, как дела?"),
        ("ru.sberbankmobile", "Сбер", "Ваш код 123456"),
        ("com.whatsapp", "Мария", ""),
    ]                                       # flags=0x2 (постоянное) отброшено


def test_parse_garbage_and_empty():
    assert notifications.parse("") == []
    assert notifications.parse(None) == []
    assert notifications.parse("nothing useful here") == []


def test_is_secret():
    for pkg in ("ru.sberbankmobile", "com.tinkoff.bank", "ru.vtb24.mobilebanking.android", "com.google.android.apps.authenticator2"):
        assert notifications.is_secret(pkg), pkg
    assert not notifications.is_secret("com.whatsapp")


@pytest.fixture
def watch_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTIFY_WATCH_FILE", tmp_path / "notify_watch.json")
    return tmp_path / "notify_watch.json"


def test_watch_list_round_trip_and_cleaning(watch_file):
    assert notifications.watched() == []
    saved = notifications.set_watched([" com.whatsapp ", "", "com.whatsapp", "org.telegram.messenger", "bad pkg!"])
    assert saved == ["com.whatsapp", "org.telegram.messenger"]
    assert notifications.watched() == saved


def test_watch_file_broken_gives_empty(watch_file):
    watch_file.write_text("{not json", "utf-8")
    assert notifications.watched() == []


def test_scan_phone_filters_packages_and_hides_text_by_default(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell", lambda serial, cmd, timeout=None: DUMP)
    got = notifications.scan_phone("S1", ["com.whatsapp", "ru.sberbankmobile"], show_text=False)
    assert got["count"] == 3
    assert all(set(i) == {"pkg"} for i in got["items"])


def test_scan_phone_shows_text_but_never_for_secret_apps(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell", lambda serial, cmd, timeout=None: DUMP)
    got = notifications.scan_phone("S1", ["com.whatsapp", "ru.sberbankmobile"], show_text=True)
    by_pkg = {}
    for i in got["items"]:
        by_pkg.setdefault(i["pkg"], []).append(i)
    assert by_pkg["com.whatsapp"][0]["title"] == "Иван"
    assert "title" not in by_pkg["ru.sberbankmobile"][0]


def test_scan_phone_empty_packages_means_all(monkeypatch):
    monkeypatch.setattr(notifications.adb, "shell", lambda serial, cmd, timeout=None: DUMP)
    assert notifications.scan_phone("S1", [], show_text=False)["count"] == 3


def test_api_watch_get_put(watch_file):
    assert api_notes.get_watch() == {"packages": []}
    assert api_notes.put_watch({"packages": ["com.whatsapp"]}) == {"packages": ["com.whatsapp"]}


def test_api_scan_over_online_phones(monkeypatch, watch_file):
    class D:
        def __init__(self, serial, name):
            self.serial, self.name, self.online = serial, name, True

    monkeypatch.setattr(api_notes.registry, "all", lambda: [D("A", "Т1"), D("B", "Т2")])
    monkeypatch.setattr(api_notes.notifications, "scan_phone",
                        lambda serial, pkgs, show_text: {"count": 1, "items": [{"pkg": "com.whatsapp"}]})
    got = api_notes.scan(packages="com.whatsapp", text=0)
    assert got["A"]["name"] == "Т1" and got["B"]["count"] == 1
```

Create `backend/tests/test_tool_notify_js.py`:

```python
"""Сводка уведомлений по приложениям (tool-notify.js: notifSummary)."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "tool-notify.js"

SCRIPT = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {toolsRegister() {}, esc: s => String(s), t: k => k};
vm.createContext(ctx);
vm.runInContext(src + ';this.sum=notifSummary', ctx);
const got = ctx.sum({
  A: {name: 'Т1', count: 2, items: [{pkg: 'com.whatsapp'}, {pkg: 'com.whatsapp'}]},
  B: {name: 'Т2', count: 1, items: [{pkg: 'com.whatsapp'}]},
  C: {name: 'Т3', count: 1, items: [{pkg: 'org.telegram.messenger'}]},
  D: {name: 'Т4', count: 0, items: []},
});
assert.deepStrictEqual(JSON.parse(JSON.stringify(got)), [
  {pkg: 'com.whatsapp', phones: 2, total: 3},
  {pkg: 'org.telegram.messenger', phones: 1, total: 1},
]);
assert.deepStrictEqual(ctx.sum({}), []);
"""


def test_notif_summary():
    node = require_node()
    out = subprocess.run([node, "-e", SCRIPT, str(JS)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_notifications.py tests/test_tool_notify_js.py -q`
Expected: FAIL `ImportError: cannot import name 'notifications' from 'farm'`.

- [ ] **Step 3: Implement backend**

`backend/farm/config.py` — рядом с `VLM_LEARNED_FILE`:

```python
NOTIFY_WATCH_FILE = Path(os.getenv("FARM_NOTIFY_WATCH_FILE", DATA_DIR / "notify_watch.json"))
```

Create `backend/farm/notifications.py`:

```python
"""Монитор уведомлений: что пришло в шторку телефонов, без открытия экранов.

Читается `dumpsys notification --noredact` — только шторка, содержимое
приложений недоступно (и не должно быть). Формат вывода зависит от версии
Android, поэтому разбор терпимый: нераспознанное пропускается, а не падает.
Текст уведомлений по умолчанию скрыт, а у банков и приложений с кодами он не
показывается никогда: код подтверждения не должен светиться в списке.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import adb, config

_REC = re.compile(r"NotificationRecord\(0x[0-9a-f]+: pkg=([\w.]+) ")
_FLAGS = re.compile(r"flags=0x([0-9a-f]+)")
_TITLE = re.compile(r"android\.title=(?:[A-Za-z]+ )?\((.*)\)\s*$", re.M)
_TEXT = re.compile(r"android\.text=(?:[A-Za-z]+ )?\((.*)\)\s*$", re.M)
_PKG = re.compile(r"^[A-Za-z][\w]*(\.[\w]+)+$")
_SECRET = re.compile(r"(bank|sber|tinkoff|vtb|alfa|raiffeisen|gazprom|pay|wallet|authenticator|otp|2fa)", re.I)
# Постоянные уведомления (FLAG_ONGOING_EVENT, FLAG_FOREGROUND_SERVICE) — не
# «новое сообщение», а работающая служба; в сводке они только мешают.
_ONGOING = 0x2 | 0x40
DUMP_CMD = "dumpsys notification --noredact"


@dataclass
class Note:
    pkg: str
    title: str
    text: str


def parse(out) -> list:
    text = out or ""
    starts = [(m.start(), m.group(1)) for m in _REC.finditer(text)]
    notes = []
    for i, (pos, pkg) in enumerate(starts):
        block = text[pos: starts[i + 1][0] if i + 1 < len(starts) else len(text)]
        flags = _FLAGS.search(block)
        if flags and int(flags.group(1), 16) & _ONGOING:
            continue
        title, body = _TITLE.search(block), _TEXT.search(block)
        notes.append(Note(pkg, title.group(1).strip() if title else "",
                          body.group(1).strip() if body else ""))
    return notes


def is_secret(pkg: str) -> bool:
    return bool(_SECRET.search(pkg or ""))


def watched() -> list:
    try:
        data = json.loads(config.NOTIFY_WATCH_FILE.read_text("utf-8"))
        return [p for p in data.get("packages", []) if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def set_watched(packages) -> list:
    clean = []
    for p in packages or []:
        p = str(p).strip()
        if _PKG.match(p) and p not in clean:
            clean.append(p)
    config.NOTIFY_WATCH_FILE.write_text(json.dumps({"packages": clean}, ensure_ascii=False), "utf-8")
    return clean


def scan_phone(serial: str, packages, show_text: bool) -> dict:
    notes = parse(adb.shell(serial, DUMP_CMD, timeout=15))
    if packages:
        notes = [n for n in notes if n.pkg in packages]
    items = []
    for n in notes:
        item = {"pkg": n.pkg}
        if show_text and not is_secret(n.pkg):
            item.update(title=n.title, text=n.text)
        items.append(item)
    return {"count": len(items), "items": items}
```

Create `backend/farm/api/notifications.py`:

```python
"""Монитор уведомлений: список отслеживаемых приложений и срез по телефонам."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Body, Query

from .. import notifications
from ..devices import registry

router = APIRouter(prefix="/api/notifications")
WORKERS = 12


@router.get("/watch")
def get_watch():
    return {"packages": notifications.watched()}


@router.put("/watch")
def put_watch(payload: dict = Body(...)):
    return {"packages": notifications.set_watched(payload.get("packages"))}


@router.get("")
def scan(packages: str = Query(""), text: int = Query(0)):
    """Срез по всем телефонам в сети: {serial: {name, count, items | error}}."""
    wanted = [p.strip() for p in packages.split(",") if p.strip()] or notifications.watched()
    phones = [d for d in registry.all() if d.online]

    def one(d):
        try:
            return d.serial, {"name": d.name, **notifications.scan_phone(d.serial, wanted, bool(text))}
        except Exception as e:  # noqa: BLE001 — один телефон не должен ронять срез
            return d.serial, {"name": d.name, "count": 0, "items": [], "error": str(e)[:200]}

    if not phones:
        return {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(phones))) as pool:
        return dict(pool.map(one, phones))
```

В тесте `test_api_scan_over_online_phones` вызывается `api_notes.scan(packages="com.whatsapp", text=0)` — функция принимает именно такие аргументы. `backend/farm/api/__init__.py`: добавить `notifications` в импорты и `router.include_router(notifications.router)`.

- [ ] **Step 4: Implement frontend**

Create `frontend/js/tool-notify.js`:

```javascript
'use strict';

/* Инструмент «Уведомления»: что пришло на телефоны. Видна только шторка
   уведомлений, не содержимое приложений. Текст по умолчанию скрыт. */

function notifSummary(results) {
    const per = new Map();
    for (const r of Object.values(results || {})) {
        const mine = new Map();
        for (const item of (r && r.items) || []) mine.set(item.pkg, (mine.get(item.pkg) || 0) + 1);
        for (const [pkg, n] of mine) {
            const g = per.get(pkg) || {pkg, phones: 0, total: 0};
            g.phones += 1;
            g.total += n;
            per.set(pkg, g);
        }
    }
    return [...per.values()].sort((a, b) => b.phones - a.phones || b.total - a.total);
}

async function notifOpen() {
    let watch = {packages: []};
    try {
        watch = await api('/api/notifications/watch');
    } catch (e) { /* список пуст — покажем форму */ }
    $('mTitle').textContent = 'Уведомления';
    $('mBody').innerHTML = `
      <p class="tool-note">Видны только уведомления в шторке; сообщения внутри приложений недоступны.
        Проверьте на одном телефоне: формат уведомлений зависит от версии Android.</p>
      <label>Приложения (по строке, пакет): <textarea id="notifPkgs" rows="3"
        placeholder="com.whatsapp">${esc(watch.packages.join('\n'))}</textarea></label>
      <div class="bp-row">
        <label><input type="checkbox" id="notifText"> показать текст (кроме банков и кодов)</label>
        <button class="sm primary" onclick="notifScan()">Проверить</button></div>
      <div id="notifOut"></div>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

async function notifScan() {
    const pkgs = $('notifPkgs').value.split(/\s+/).map(s => s.trim()).filter(Boolean);
    const out = $('notifOut');
    out.textContent = 'Проверяю телефоны…';
    try {
        const saved = await api('/api/notifications/watch', {
            method: 'PUT', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({packages: pkgs})});
        const res = await api(`/api/notifications?packages=${encodeURIComponent(saved.packages.join(','))}&text=${$('notifText').checked ? 1 : 0}`);
        const sum = notifSummary(res);
        out.innerHTML = sum.length
            ? `<table class="tool-table"><thead><tr><th>Приложение</th><th>Телефонов</th><th>Всего</th></tr></thead><tbody>
                ${sum.map(g => `<tr><td>${esc(g.pkg)}</td><td>${g.phones}</td><td>${g.total}</td></tr>`).join('')}</tbody></table>`
              + Object.values(res).filter(r => (r.items || []).some(i => i.title)).map(r =>
                  `<p><b>${esc(r.name)}</b>: ` + r.items.filter(i => i.title)
                      .map(i => `${esc(i.title)} — ${esc(i.text || '')}`).join('; ') + '</p>').join('')
            : '<p class="tool-note">Новых уведомлений нет.</p>';
    } catch (e) {
        out.textContent = e.message;
    }
}

toolsRegister({id: 'notify', icon: 'info', title: 'Уведомления',
               sub: 'где пришло сообщение или код', open: notifOpen});
```

`frontend/index.html`: после `tool-backup.js` добавить `<script src="js/tool-notify.js"></script>`.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_notifications.py tests/test_tool_notify_js.py -q`
Expected: all PASS.

```bash
git add backend/farm/notifications.py backend/farm/api/notifications.py backend/farm/api/__init__.py backend/farm/config.py frontend/js/tool-notify.js frontend/index.html backend/tests/test_notifications.py backend/tests/test_tool_notify_js.py
git commit -m "F5: монитор уведомлений по телефонам"
```

---

### Task 9: F6 — контакты пакетом

**Files:**
- Create: `backend/farm/contacts.py`
- Modify: `backend/farm/api/screen.py` (действия `contacts_add`, `contacts_clear`), `frontend/js/bulk.js` (плитка и панель)
- Test: `backend/tests/test_contacts.py`

**Interfaces:**
- Produces:
  - `contacts.generate(prefix: str, length: int, count: int, rng=None) -> list[str]` (`ValueError` по-русски)
  - `contacts.parse_file(text: str) -> tuple[list[dict], int]` — `([{"name", "number"}], пропущено)`
  - `contacts.insert_scripts(items: list[dict], chunk: int = 15) -> list[str]` — shell-скрипты, по `chunk` контактов в каждом
  - `contacts.CLEAR_SCRIPT: str`
  - `contacts.check_output(out: str) -> None` — `RuntimeError("этот телефон не даёт писать контакты …")` при отказе
  - `screen.ACTIONS["contacts_add"]` — тело `{type, items?: [...], generate?: {prefix, length, count}}` → `{"added": n}`; `screen.ACTIONS["contacts_clear"]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_contacts.py`:

```python
"""Контакты пакетом: номера, файл, shell-скрипты, ответы телефона."""
import random

import pytest

from farm import contacts
from farm.api import screen


def test_generate_unique_numbers_with_prefix_and_length():
    nums = contacts.generate("+7999", 11, 50, random.Random(1))
    assert len(nums) == len(set(nums)) == 50
    assert all(n.startswith("+7999") and len(n.lstrip("+")) == 11 for n in nums)


@pytest.mark.parametrize("prefix,length,count", [
    ("+7abc", 11, 5), ("+7999", 4, 5), ("+7999", 20, 5), ("+7999", 11, 0), ("+7999", 11, 5000),
    ("+79991234567", 11, 5),          # префикс уже длиной с номер — нечему случайничать
])
def test_generate_rejects_bad_input(prefix, length, count):
    with pytest.raises(ValueError):
        contacts.generate(prefix, length, count)


def test_generate_cannot_exceed_possible_numbers():
    with pytest.raises(ValueError):
        contacts.generate("+799912345", 11, 500)         # свободно две цифры — максимум 100


def test_parse_file_formats_and_skips():
    text = "+79991112233\nИван;+7 (999) 222-33-44\nМария, 89993334455\n\nмусор\n12\n"
    items, skipped = contacts.parse_file(text)
    assert items == [
        {"name": "+79991112233", "number": "+79991112233"},
        {"name": "Иван", "number": "+79992223344"},
        {"name": "Мария", "number": "89993334455"},
    ]
    assert skipped == 2


def test_parse_file_limits_count():
    items, _ = contacts.parse_file("\n".join(f"+7999{i:07d}" for i in range(3000)))
    assert len(items) == contacts.MAX_ITEMS


def test_insert_scripts_chunk_and_contents():
    items = [{"name": f"Имя {i}", "number": f"+7999000{i:04d}"} for i in range(20)]
    scripts = contacts.insert_scripts(items, chunk=15)
    assert len(scripts) == 2
    first = scripts[0]
    assert first.count("content://com.android.contacts/raw_contacts") >= 15
    assert "vnd.android.cursor.item/name" in first and "vnd.android.cursor.item/phone_v2" in first
    assert "+79990000000" in first


def test_insert_scripts_cannot_inject_shell():
    evil = [{"name": "x'; rm -rf /; echo '", "number": "+79991112233; reboot"}]
    script = contacts.insert_scripts(evil)[0]
    # кавычки и «;» из имени вырезаны, имя осталось безобидным текстом в кавычках
    assert "data1:s:'x rm -rf  echo'" in script
    assert "'; rm" not in script
    # буквы из номера вырезаны, команде reboot взяться неоткуда
    assert "reboot" not in script and "data1:s:'+79991112233'" in script


def test_insert_scripts_drops_contacts_with_bad_numbers():
    assert contacts.insert_scripts([{"name": "A", "number": "12"}]) == []


def test_clear_script():
    assert "content delete" in contacts.CLEAR_SCRIPT and "raw_contacts" in contacts.CLEAR_SCRIPT


def test_check_output_raises_for_permission_denials():
    for out in ("java.lang.SecurityException: Permission Denial", "Error: permission denied", "Exception occurred"):
        with pytest.raises(RuntimeError) as e:
            contacts.check_output(out)
        assert "не даёт" in str(e.value)
    contacts.check_output("Row: 0 _id=5\n")
    contacts.check_output("")


@pytest.fixture
def shell(monkeypatch):
    calls = []
    monkeypatch.setattr(screen.adb, "shell",
                        lambda serial, cmd, timeout=None: calls.append((serial, cmd)) or "")
    return calls


def test_action_add_items(shell):
    items = [{"name": "Иван", "number": "+79991112233"}]
    res = screen.ACTIONS["contacts_add"]("S1", {"type": "contacts_add", "items": items})
    assert res == {"ok": True, "added": 1}
    assert len(shell) == 1 and "+79991112233" in shell[0][1]


def test_action_add_generated_is_different_per_phone(shell):
    body = {"type": "contacts_add", "generate": {"prefix": "+7999", "length": 11, "count": 5}}
    screen.ACTIONS["contacts_add"]("S1", body)
    screen.ACTIONS["contacts_add"]("S2", body)
    assert shell[0][1] != shell[1][1]


def test_action_add_needs_something(shell):
    with pytest.raises(ValueError):
        screen.ACTIONS["contacts_add"]("S1", {"type": "contacts_add"})
    assert shell == []


def test_action_add_stops_on_denial(monkeypatch):
    monkeypatch.setattr(screen.adb, "shell", lambda s, c, timeout=None: "java.lang.SecurityException: Permission Denial")
    with pytest.raises(RuntimeError):
        screen.ACTIONS["contacts_add"]("S1", {"items": [{"name": "A", "number": "+79991112233"}]})


def test_action_clear(shell):
    assert screen.ACTIONS["contacts_clear"]("S1", {"type": "contacts_clear"}) == {"ok": True}
    assert "content delete" in shell[0][1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_contacts.py -q`
Expected: FAIL `ImportError: cannot import name 'contacts' from 'farm'`.

- [ ] **Step 3: Implement**

Create `backend/farm/contacts.py`:

```python
"""Контакты пакетом: номера, разбор файла и shell-скрипты для телефона.

Чистый модуль. Номера и имена проходят через жёсткую очистку: в shell
телефона попадает только то, что мы собрали из безопасных символов, а не
строка пользователя как есть. Запись идёт через `content insert` в базу
контактов; не все прошивки это разрешают, поэтому отказ телефона — понятное
сообщение по этому телефону, а не падение всей пачки.
"""
from __future__ import annotations

import random
import re

MAX_ITEMS = 2000
MAX_GENERATE = 1000
_DIGITS = re.compile(r"[^\d+]")
_NAME_BAD = re.compile(r"[^\w .\-]", re.U)
_NUMBER = re.compile(r"^\+?\d{7,15}$")
RAW = "content://com.android.contacts/raw_contacts"
DATA = "content://com.android.contacts/data"
CLEAR_SCRIPT = f"content delete --uri {DATA}; content delete --uri {RAW}"
_DENIED = ("securityexception", "permission denial", "permission denied", "exception occurred", "error:")


def _clean_number(raw: str):
    num = _DIGITS.sub("", raw or "")
    if num.count("+") > 1 or ("+" in num and not num.startswith("+")):
        return None
    return num if _NUMBER.match(num) else None


def _clean_name(raw: str, fallback: str) -> str:
    name = _NAME_BAD.sub("", raw or "").strip()[:40]
    return name or fallback


def generate(prefix: str, length: int, count: int, rng=None) -> list:
    """`count` разных номеров длиной `length` цифр с общим началом `prefix`."""
    rng = rng or random
    prefix = (prefix or "").strip()
    if not re.fullmatch(r"\+?\d{1,10}", prefix):
        raise ValueError("начало номера — цифры, можно с плюсом в начале")
    length, count = int(length), int(count)
    if not 7 <= length <= 15:
        raise ValueError("длина номера — от 7 до 15 цифр")
    if not 1 <= count <= MAX_GENERATE:
        raise ValueError(f"количество — от 1 до {MAX_GENERATE}")
    free = length - len(prefix.lstrip("+"))
    if free < 1:
        raise ValueError("начало номера уже такой длины, как весь номер")
    if count > 10 ** free:
        raise ValueError(f"после начала остаётся {free} цифр — столько разных номеров не набрать")
    seen = set()
    while len(seen) < count:
        seen.add(prefix + "".join(rng.choice("0123456789") for _ in range(free)))
    return sorted(seen)


def parse_file(text: str):
    """Строки «номер» или «имя;номер» / «имя, номер» → контакты. Негодные строки считаются."""
    items, skipped = [], 0
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r"[;,\t]", line, maxsplit=1)
        number = _clean_number(parts[-1])
        if number is None:
            skipped += 1
            continue
        name = _clean_name(parts[0], number) if len(parts) == 2 else number
        items.append({"name": name, "number": number})
        if len(items) >= MAX_ITEMS:
            break
    return items, skipped


def _one(name: str, number: str) -> str:
    return (
        f"content insert --uri {RAW} --bind account_type:n: --bind account_name:n:; "
        f"RID=$(content query --uri {RAW} --projection _id --sort '_id DESC' | head -n 1 | sed 's/.*_id=\\([0-9]*\\).*/\\1/'); "
        f"content insert --uri {DATA} --bind raw_contact_id:i:$RID "
        f"--bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:'{name}'; "
        f"content insert --uri {DATA} --bind raw_contact_id:i:$RID "
        f"--bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:'{number}' --bind data2:i:2"
    )


def insert_scripts(items, chunk: int = 15) -> list:
    """Скрипты по `chunk` контактов: десять вызовов adb вместо сотни."""
    safe = []
    for item in items:
        number = _clean_number(item.get("number"))
        if number:
            safe.append((_clean_name(item.get("name"), number), number))
    return ["; ".join(_one(n, p) for n, p in safe[i:i + chunk]) for i in range(0, len(safe), chunk)]


def check_output(out: str) -> None:
    low = (out or "").lower()
    if any(mark in low for mark in _DENIED):
        raise RuntimeError("этот телефон не даёт писать контакты через adb — "
                           "добавьте их на нём вручную или импортом файла .vcf")
```

`backend/farm/api/screen.py`: к импортам добавить `from .. import contacts` (в строку `from .. import adb, config, control, streaming`), перед `ACTIONS = {` вставить:

```python
def _contacts_add(serial, p):
    """Контакты на телефон: список из файла (одинаковый у всех) или случайные
    по шаблону (у каждого телефона свои — одинаковые «друзья» у сорока
    аккаунтов выглядят подозрительно)."""
    if p.get("items"):
        items = p["items"]
    elif p.get("generate"):
        g = p["generate"]
        numbers = contacts.generate(g.get("prefix"), g.get("length"), g.get("count"))
        items = [{"name": n, "number": n} for n in numbers]
    else:
        raise ValueError("нет ни списка контактов, ни шаблона номеров")
    for script in contacts.insert_scripts(items):
        contacts.check_output(adb.shell(serial, script, timeout=120))
    return {"ok": True, "added": len(items)}


def _contacts_clear(serial, p):
    contacts.check_output(adb.shell(serial, contacts.CLEAR_SCRIPT, timeout=60))
    return {"ok": True}
```

и в `ACTIONS` добавить `"contacts_add": _contacts_add, "contacts_clear": _contacts_clear,`.

Во фронтенде `frontend/js/bulk.js` — плитка в группу «Текст, группа и теги» (после «Каждому своё»):

```javascript
      ${tile("bulkPanel('contacts')", 'layers', 'Контакты', 'добавить пачкой или очистить', 'contacts')}
```

ключ панели в `bulkPanel`:

```javascript
        contacts: `<div class="bp-row">
            <input id="bulkCtPrefix" placeholder="начало номера, например +7999" aria-label="Начало номера">
            <input id="bulkCtLen" type="number" value="11" min="7" max="15" aria-label="Длина номера">
            <input id="bulkCtCount" type="number" value="20" min="1" max="1000" aria-label="Сколько">
            <button class="sm primary" onclick="bulkContactsGenerate()">Случайные, у каждого свои</button></div>
          <div class="bp-row">
            <input type="file" accept=".txt,.csv" aria-label="Файл" onchange="bulkContactsFile(this.files[0])">
            <button class="sm danger" onclick="bulkContactsClear(event)"><span>Очистить все контакты</span></button></div>
          <small class="dim" id="bulkCtInfo">Файл: «номер» или «имя;номер» по строке. Проверьте на одном телефоне: не все прошивки дают писать контакты.</small>`,
```

и функции (рядом с `bulkSendLines`):

```javascript
function bulkContactsGenerate() {
    const prefix = $('bulkCtPrefix').value.trim();
    if (!prefix) return toast('впишите начало номера', 'bad');
    bulkAction({type: 'contacts_add', generate: {
        prefix, length: Number($('bulkCtLen').value), count: Number($('bulkCtCount').value)}}, 'Контакты');
}

async function bulkContactsFile(file) {
    if (!file) return;
    const buf = await file.arrayBuffer();
    let text;
    try {
        text = new TextDecoder('utf-8', {fatal: true}).decode(buf);
    } catch (e) {
        text = new TextDecoder('windows-1251').decode(buf);
    }
    const items = bulkContactsParse(text);
    $('bulkCtInfo').textContent = items.length ? `Из файла: ${items.length} контактов` : 'В файле нет номеров';
    if (items.length) bulkAction({type: 'contacts_add', items}, 'Контакты');
}

function bulkContactsParse(text) {
    const out = [];
    for (const line of String(text || '').split(/\r?\n/)) {
        const parts = line.trim().split(/[;,\t]/);
        const number = (parts[parts.length - 1] || '').replace(/[^\d+]/g, '');
        if (!/^\+?\d{7,15}$/.test(number)) continue;
        out.push({name: parts.length > 1 ? parts[0].trim() : number, number});
        if (out.length >= 2000) break;
    }
    return out;
}

function bulkContactsClear(ev) {
    const n = bulkTargets().length;
    if (!armConfirm(ev.currentTarget, `Стереть ВСЕ контакты на ${n} ${declOfNum(n, ['телефоне', 'телефонах', 'телефонах'])}?`)) return;
    bulkAction({type: 'contacts_clear'}, 'Очистка контактов');
}
```

- [ ] **Step 4: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_contacts.py tests/test_bulk_lines_js.py -q`
Expected: all PASS.

```bash
git add backend/farm/contacts.py backend/farm/api/screen.py frontend/js/bulk.js backend/tests/test_contacts.py
git commit -m "F6: контакты пакетом — случайные, из файла, очистка"
```

---

### Task 10: F7 — документация API с проверкой маршрутов

**Files:**
- Create: `docs/public-api.md`, `frontend/js/tool-api.js`, `backend/tests/test_public_api_doc.py`
- Modify: `frontend/index.html` (скрипт)

**Interfaces:**
- Consumes: существующие маршруты `/api/*` и защиту `FARM_TOKEN` (`farm/security.py`, заголовок `X-Farm-Token`).
- Produces: документ, в котором каждая строка вида «`METHOD /api/...`» в таблице маршрутов существует в схеме OpenAPI.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_public_api_doc.py`:

```python
"""docs/public-api.md не врёт: каждый упомянутый маршрут существует в ферме."""
import re
from pathlib import Path

from farm.server import create_app

DOC = Path(__file__).resolve().parents[2] / "docs" / "public-api.md"
ROW = re.compile(r"^\|\s*`(GET|POST|PUT|PATCH|DELETE) (/api/[^`]+)`", re.M)


def _paths():
    return create_app().openapi()["paths"]


def test_doc_exists_and_has_routes():
    assert DOC.is_file()
    assert len(ROW.findall(DOC.read_text("utf-8"))) >= 10


def test_every_documented_route_exists():
    paths = _paths()
    missing = []
    for method, path in ROW.findall(DOC.read_text("utf-8")):
        if method.lower() not in paths.get(path, {}):
            missing.append(f"{method} {path}")
    assert not missing, f"в документе есть несуществующие маршруты: {missing}"


def test_doc_explains_token_and_address():
    text = DOC.read_text("utf-8")
    assert "FARM_TOKEN" in text and "X-Farm-Token" in text and "127.0.0.1:8777" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_public_api_doc.py -q`
Expected: FAIL (`docs/public-api.md` нет).

- [ ] **Step 3: Write the document**

Create `docs/public-api.md`:

````markdown
# Управление фермой из своих программ

Всё, что можно сделать мышью на сайте фермы, доступно и по HTTP. Интерактивная
справка по всем маршрутам открывается на работающей ферме:
`http://127.0.0.1:8777/docs`.

## Адрес и защита

- Ферма слушает `127.0.0.1:8777` — только ваш компьютер. Ничего настраивать не
  нужно.
- Если вы открыли ферму в сеть (`FARM_HOST=0.0.0.0`), обязательно задайте
  секрет: переменная окружения `FARM_TOKEN`. Тогда каждый запрос должен нести
  заголовок `X-Farm-Token: <секрет>`; без него ферма отвечает отказом.
- Запросы, меняющие данные, из браузера принимаются только со страницы самой
  фермы. Скриптам (curl, Python) это не мешает: у них нет заголовка `Origin`.

```bash
export FARM_TOKEN=мой-длинный-секрет
FARM_HOST=0.0.0.0 ./run.sh
curl -H "X-Farm-Token: $FARM_TOKEN" http://192.168.1.10:8777/api/devices
```

## Самое нужное

| Маршрут | Что делает |
|---|---|
| `GET /api/status` | сколько телефонов в сети, сколько задач |
| `GET /api/devices` | все телефоны: имя, заряд, температура, память, группа, теги |
| `GET /api/devices/{serial}/screenshot` | снимок экрана телефона (JPEG) |
| `GET /api/devices/{serial}/frame` | свежий кадр экрана |
| `POST /api/devices/{serial}/action` | одно действие на одном телефоне |
| `POST /api/bulk/action` | то же действие на нескольких телефонах |
| `POST /api/bulk/text_lines` | «каждому своё»: строка файла — на свой телефон |
| `POST /api/bulk/display` | текущее разрешение выбранных телефонов |
| `GET /api/scenarios` | список сценариев и их настройки |
| `POST /api/run` | запустить сценарий на телефонах |
| `GET /api/jobs` | список запусков |
| `GET /api/jobs/{job_id}` | один запуск: статус, журнал |
| `POST /api/jobs/{job_id}/cancel` | остановить запуск |
| `GET /api/notifications` | уведомления в шторках телефонов |
| `POST /api/backup/export` | скачать резервную копию (zip) |

`{serial}` — серийный номер телефона из `GET /api/devices` (поле `serial`).

## Примеры

Нажать в центр экрана на одном телефоне (координаты — доли экрана от 0 до 1):

```bash
curl -X POST http://127.0.0.1:8777/api/devices/ABC123/action \
     -H 'Content-Type: application/json' \
     -d '{"type": "tap", "x": 0.5, "y": 0.5}'
```

Открыть ссылку на всех телефонах группы:

```bash
curl -X POST http://127.0.0.1:8777/api/bulk/action \
     -H 'Content-Type: application/json' \
     -d '{"serials": ["ABC123", "DEF456"], "action": {"type": "url", "url": "https://example.com"}}'
```

Запустить сценарий и дождаться конца (Python):

```python
import time
import requests

farm = "http://127.0.0.1:8777"
head = {}   # {"X-Farm-Token": "..."} если задан FARM_TOKEN

run = requests.post(f"{farm}/api/run", headers=head, json={
    "scenario": "smoke", "serials": ["ABC123"], "params": {}}).json()
job_id = run["jobs"][0]["id"]
while True:
    job = requests.get(f"{farm}/api/jobs/{job_id}", headers=head).json()
    if job["status"] in ("passed", "failed", "cancelled"):
        print(job["status"])
        break
    time.sleep(2)
```

Виды действий (`type`): `tap`, `long_tap`, `swipe`, `text`, `key`, `launch`,
`stop`, `url`, `unlock`, `shell`, `screen_off`, `rotate`, `resolution_set`,
`resolution_reset`, `contacts_add`, `contacts_clear`. Поля каждого видно в
справке `/docs`.

## Осторожно

- `shell` выполняет любую команду на телефоне. Не открывайте ферму в сеть без
  `FARM_TOKEN`.
- Пароли аккаунтов лежат в `GET /api/accounts/{id}/password`, ключ adb — в
  резервной копии. Берегите токен так же, как их.
````

(Если у задачи в `GET /api/jobs/{job_id}` поля называются иначе, чем в примере (`status`/`id`), — поправьте пример по `GET /api/jobs` на живой ферме; тест проверяет только существование маршрутов.)

- [ ] **Step 4: Add the tool tile**

Create `frontend/js/tool-api.js`:

```javascript
'use strict';

/* Инструмент «Для программистов»: адрес и справка API. Сам API уже есть —
   здесь только подсказка, куда смотреть и как закрыть доступ из сети. */

function apiToolOpen() {
    const base = location.origin;
    $('mTitle').textContent = 'Для программистов';
    $('mBody').innerHTML = `
      <p class="tool-note">Всё, что делает сайт, можно делать из своих программ по HTTP.</p>
      <ul>
        <li>Справка по всем действиям: <a href="${esc(base)}/docs" target="_blank" rel="noopener">${esc(base)}/docs</a></li>
        <li>Адрес API: <code>${esc(base)}/api</code></li>
        <li>Описание с примерами: файл <code>docs/public-api.md</code> в папке фермы</li>
      </ul>
      <p class="tool-warn">Если открываете ферму в сеть, задайте секрет <code>FARM_TOKEN</code> — иначе любой в сети управляет вашими телефонами.</p>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

toolsRegister({id: 'api', icon: 'external', title: 'Для программистов',
               sub: 'управлять фермой из своих программ', open: apiToolOpen});
```

`frontend/index.html`: после `tool-notify.js` добавить `<script src="js/tool-api.js"></script>`.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_public_api_doc.py tests/test_tools_js.py -q`
Expected: all PASS. Если `test_every_documented_route_exists` показал несуществующий маршрут — исправить строку таблицы, а не тест.

```bash
git add docs/public-api.md frontend/js/tool-api.js frontend/index.html backend/tests/test_public_api_doc.py
git commit -m "F7: документация API для своих программ и вкладка в «Инструментах»"
```

---

### Task 11: F9 — черновик сценария по описанию

**Files:**
- Create: `backend/farm/vlm/plan.py`, `frontend/js/tool-draft.js`
- Modify: `backend/farm/api/vlm.py` (маршрут `POST /api/vlm/plan`), `frontend/index.html` (скрипт)
- Test: `backend/tests/test_vlm_plan.py`

**Interfaces:**
- Consumes (существующее): `vlm.settings.get()` (`enabled, url, max_per_job, max_per_day`), `vlm.client.ask(image_bytes, prompt)`, `vlm.usage.reserve(job_key, max_per_job, max_per_day) -> (bool, str)`, `vlm.usage.refund(job_key)`, `vlm.locate.safety.secret_goal(text)`, `vlm.locate.screen_gate(ctx_like, image) -> truthy|falsy`, `control.screenshot(serial, quality=85)`, `recorder.steps.normalize_steps(items)` (бросает `StepError`).
- Produces:
  - `plan.PlanError(Exception)`
  - `plan.ALLOWED: dict` — вид шага → обязательные поля
  - `plan.build_prompt(task: str) -> str`
  - `plan.parse_steps(text: str) -> list[dict]` — шаги `{"kind", "args"}`; `PlanError` если пусто
  - `plan.plan(serial: str, task: str) -> list[dict]`
  - `plan.recipe_for(task: str, steps: list) -> dict` — тело для `POST /api/recorder/save`
  - `POST /api/vlm/plan` тело `{"serial", "task"}` → `{"steps": [...], "recipe": {...}}`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_vlm_plan.py`:

```python
"""Черновик сценария по описанию: разбор ответа модели, ограничения, рецепт."""
from types import SimpleNamespace

import pytest

from farm.vlm import plan

GOOD = """Вот шаги:
```json
[
  {"kind": "launch_app", "args": {"package": "org.telegram.messenger"}},
  {"kind": "sleep", "args": {"seconds": 2}},
  {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.8, "x2": 0.5, "y2": 0.3}},
  {"kind": "type", "args": {"value": "привет"}},
  {"kind": "key", "args": {"name": "back"}}
]
```"""


def test_parse_steps_from_fenced_json():
    steps = plan.parse_steps(GOOD)
    assert [s["kind"] for s in steps] == ["launch_app", "sleep", "swipe", "type", "key"]
    assert steps[0]["args"] == {"package": "org.telegram.messenger"}


def test_parse_steps_plain_array_without_fences():
    assert plan.parse_steps('[{"kind": "sleep", "args": {"seconds": 1}}]')[0]["kind"] == "sleep"


def test_parse_steps_drops_unknown_kinds_and_missing_args():
    text = ('[{"kind": "shell", "args": {"cmd": "rm -rf /"}},'
            ' {"kind": "swipe", "args": {"x1": 0.5}},'
            ' {"kind": "tap", "args": {"x": 0.5, "y": 0.5}},'
            ' "junk", 5, {"kind": "sleep", "args": {"seconds": "abc"}}]')
    steps = plan.parse_steps(text)
    assert [s["kind"] for s in steps] == ["tap"]


def test_parse_steps_never_lets_shell_through():
    with pytest.raises(plan.PlanError):
        plan.parse_steps('[{"kind": "shell", "args": {"cmd": "reboot"}}]')


def test_parse_steps_clamps_numbers_and_caps_count():
    many = ",".join('{"kind": "sleep", "args": {"seconds": 1}}' for _ in range(80))
    assert len(plan.parse_steps(f"[{many}]")) == plan.MAX_STEPS
    s = plan.parse_steps('[{"kind": "tap", "args": {"x": 5, "y": -2}}]')[0]["args"]
    assert 0 <= s["x"] <= 1 and 0 <= s["y"] <= 1
    sl = plan.parse_steps('[{"kind": "sleep", "args": {"seconds": 99999}}]')[0]["args"]
    assert sl["seconds"] <= plan.MAX_SLEEP


@pytest.mark.parametrize("text", ["", "no json here", "[]", '{"kind": "sleep"}', "[1, 2]"])
def test_parse_steps_empty_raises(text):
    with pytest.raises(plan.PlanError):
        plan.parse_steps(text)


def test_build_prompt_contains_task_and_allowed_kinds():
    p = plan.build_prompt("открой Telegram")
    assert "открой Telegram" in p
    for kind in plan.ALLOWED:
        assert kind in p
    assert "shell" not in p


def test_recipe_for_is_valid_for_recorder():
    from farm.recorder import steps as schema
    steps = plan.parse_steps(GOOD)
    recipe = plan.recipe_for("открой Telegram и пролистай ленту", steps)
    assert recipe["key"].startswith("chernovik_")
    assert recipe["meta"]["name"].startswith("Черновик:")
    schema.normalize_steps(recipe["steps"])              # не бросает


@pytest.fixture
def ready(monkeypatch):
    cfg = SimpleNamespace(enabled=True, url="http://x", max_per_job=5, max_per_day=50)
    monkeypatch.setattr(plan.settings, "get", lambda: cfg)
    monkeypatch.setattr(plan.control, "screenshot", lambda serial, quality=85: b"img")
    monkeypatch.setattr(plan.loc, "screen_gate", lambda c, image: False)
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: False)
    monkeypatch.setattr(plan.usage, "reserve", lambda job, a, b: (True, ""))
    monkeypatch.setattr(plan.usage, "refund", lambda job: None)
    monkeypatch.setattr(plan.client, "ask", lambda image, prompt, cfg=None: GOOD)
    return cfg


def test_plan_happy_path(ready):
    assert [s["kind"] for s in plan.plan("S1", "открой Telegram")][0] == "launch_app"


def test_plan_refuses_when_assistant_is_off(ready, monkeypatch):
    monkeypatch.setattr(plan.settings, "get", lambda: SimpleNamespace(enabled=False, url="", max_per_job=1, max_per_day=1))
    with pytest.raises(plan.PlanError) as e:
        plan.plan("S1", "x")
    assert "выключен" in str(e.value)


def test_plan_refuses_secret_goals_and_secure_screens(ready, monkeypatch):
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: True)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "введи пароль")
    monkeypatch.setattr(plan.loc.safety, "secret_goal", lambda text: False)
    monkeypatch.setattr(plan.loc, "screen_gate", lambda c, image: True)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")


def test_plan_refuses_when_limit_reached(ready, monkeypatch):
    monkeypatch.setattr(plan.usage, "reserve", lambda job, a, b: (False, "лимит"))
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")


def test_plan_refunds_quota_when_model_fails(ready, monkeypatch):
    refunded = []
    monkeypatch.setattr(plan.usage, "refund", lambda job: refunded.append(job))

    def boom(image, prompt, cfg=None):
        raise RuntimeError("нет связи")
    monkeypatch.setattr(plan.client, "ask", boom)
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "x")
    assert refunded


def test_plan_rejects_empty_task(ready):
    with pytest.raises(plan.PlanError):
        plan.plan("S1", "   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_vlm_plan.py -q`
Expected: FAIL `ImportError: cannot import name 'plan' from 'farm.vlm'`.

- [ ] **Step 3: Implement backend**

Create `backend/farm/vlm/plan.py`:

```python
"""Черновик сценария по описанию словами.

Человек пишет задачу («открой Telegram, пролистай ленту»), нейросеть смотрит
на экран и предлагает шаги. Результат — ЧЕРНОВИК: он сохраняется как обычный
сценарий конструктора, который человек читает, правит и сам проверяет на
одном телефоне. Автоматического выполнения нет.

Ограничения те же, что у остальной нейросети фермы: выключена по умолчанию,
кадры уходят наружу только по согласию, секретные цели и защищённые экраны
отсекаются, вызовы идут в общий лимит. Модели разрешены только безопасные
виды шагов: `shell` и прочее, что меняет телефон вне приложения, — нет.
"""
from __future__ import annotations

import json
import re
import time

from .. import control
from ..recorder import steps as schema
from . import client, locate as loc, settings, usage

MAX_STEPS = 30
MAX_SLEEP = 60
JOB_KEY = "plan"
# Вид шага → обязательные поля. Числа 0..1 для координат; ограничения ниже.
ALLOWED = {
    "launch_app": ("package",),
    "open_url": ("url",),
    "tap": ("x", "y"),
    "swipe": ("x1", "y1", "x2", "y2"),
    "type": ("value",),
    "key": ("name",),
    "sleep": ("seconds",),
}
_COORDS = ("x", "y", "x1", "y1", "x2", "y2")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

PROMPT = (
    "You help to draft an automation recipe for an Android phone. The user's task: {task}\n"
    "Look at the screenshot (the current phone screen) and answer with ONLY a JSON array of steps, "
    "no explanations. Allowed step kinds and their args: {kinds}. "
    "Coordinates are fractions of the screen from 0 to 1. At most {limit} steps. "
    "Never include passwords, payment or personal data."
)


class PlanError(Exception):
    """Понятная причина, по которой черновика нет."""


def build_prompt(task: str) -> str:
    kinds = "; ".join(f'{k}({", ".join(args)})' for k, args in ALLOWED.items())
    return PROMPT.format(task=task.strip(), kinds=kinds, limit=MAX_STEPS)


def _number(value, lo, hi):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _clean(step):
    if not isinstance(step, dict) or step.get("kind") not in ALLOWED:
        return None
    args = step.get("args")
    if not isinstance(args, dict):
        return None
    kind, out = step["kind"], {}
    for name in ALLOWED[kind]:
        if name not in args:
            return None
        value = args[name]
        if name in _COORDS:
            value = _number(value, 0.0, 1.0)
        elif name == "seconds":
            value = _number(value, 0.0, MAX_SLEEP)
        else:
            value = str(value).strip()[:500]
            if not value:
                return None
        if value is None:
            return None
        out[name] = value
    return {"kind": kind, "args": out}


def parse_steps(text: str) -> list:
    """Шаги из ответа модели: только разрешённые виды, числа в границах."""
    raw = text or ""
    fenced = _FENCE.search(raw)
    body = fenced.group(1) if fenced else raw
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        raise PlanError("модель не вернула список шагов")
    try:
        items = json.loads(body[start:end + 1])
    except ValueError:
        raise PlanError("ответ модели не удалось прочитать")
    steps = [s for s in (_clean(i) for i in items) if s][:MAX_STEPS]
    if not steps:
        raise PlanError("в ответе модели нет подходящих шагов")
    return steps


def plan(serial: str, task: str) -> list:
    task = (task or "").strip()
    if not task:
        raise PlanError("опишите задачу словами")
    cfg = settings.get()
    if not (cfg.enabled and cfg.url):
        raise PlanError("нейросеть-помощник выключен — включите его в настройках (значок в шапке)")
    if loc.safety.secret_goal(task):
        raise PlanError("в описании пароль или платёжные данные — такое нейросети не отправляем")
    image = control.screenshot(serial, quality=85)

    class _C:       # screen_gate смотрит только на serial
        pass
    c = _C()
    c.serial = serial
    if loc.screen_gate(c, image):
        raise PlanError("экран защищён от снимков — нейросети его не показываем")
    ok, why = usage.reserve(JOB_KEY, cfg.max_per_job, cfg.max_per_day)
    if not ok:
        raise PlanError(why or "лимит запросов к нейросети на сегодня исчерпан")
    try:
        reply = client.ask(image, build_prompt(task))
    except Exception as e:  # noqa: BLE001
        usage.refund(JOB_KEY)           # ответа не было — квоту не тратим
        raise PlanError(f"нейросеть не ответила: {e}")
    return parse_steps(reply)


def recipe_for(task: str, steps: list) -> dict:
    """Тело для POST /api/recorder/save; проверку шагов делает сам конструктор."""
    title = " ".join(task.split())[:40]
    return {"key": time.strftime("chernovik_%Y%m%d_%H%M%S"),
            "meta": {"name": f"Черновик: {title}",
                     "description": "Составлен нейросетью по описанию. Проверьте шаги и запустите на одном телефоне.",
                     "watch_popups": True, "human": True},
            "params": {}, "steps": steps}
```

В `backend/farm/api/vlm.py` — добавить импорт `from ..vlm import plan as vlm_plan` (по образцу существующих импортов файла) и маршрут:

```python
@router.post("/plan")
def make_plan(payload: dict = Body(...)):
    """Черновик сценария по описанию. Ничего не сохраняет и не запускает."""
    serial, task = payload.get("serial"), payload.get("task")
    if not serial:
        raise HTTPException(400, "не выбран телефон для снимка экрана")
    try:
        steps = vlm_plan.plan(serial, task)
    except vlm_plan.PlanError as e:
        raise HTTPException(400, str(e))
    return {"steps": steps, "recipe": vlm_plan.recipe_for(task, steps)}
```

(Проверить, что в файле уже импортированы `Body` и `HTTPException`; роутер там называется `router`, префикс `/api/vlm`.)

- [ ] **Step 4: Implement frontend**

Create `frontend/js/tool-draft.js`:

```javascript
'use strict';

/* Инструмент «Черновик по описанию»: пишете задачу словами, нейросеть
   предлагает шаги. Это черновик: он сохраняется как обычный сценарий, который
   надо проверить на одном телефоне. Нужен включённый помощник (значок в шапке). */

let DRAFT = null;

function draftStepText(step) {
    const a = step.args || {};
    return {launch_app: `открыть приложение ${a.package}`, open_url: `открыть ссылку ${a.url}`,
            tap: `нажать в точку (${a.x}, ${a.y})`, swipe: `провести (${a.x1}, ${a.y1}) → (${a.x2}, ${a.y2})`,
            type: `ввести «${a.value}»`, key: `клавиша ${a.name}`, sleep: `подождать ${a.seconds} с`}[step.kind] || step.kind;
}

function draftOpen() {
    const phones = (S.devices || []).filter(d => d.online);
    $('mTitle').textContent = 'Черновик по описанию';
    $('mBody').innerHTML = `
      <p class="tool-note">Опишите, что делать. Нейросеть посмотрит на экран выбранного телефона и предложит шаги.
        Кадр экрана уходит во внешнюю модель — помощник должен быть включён вами.</p>
      <label>Телефон для снимка: <select id="draftPhone">${phones.map(d =>
        `<option value="${esc(d.serial)}">${esc(d.name)}</option>`).join('')}</select></label>
      <textarea id="draftTask" rows="3" placeholder="Например: открой Telegram и пролистай ленту вниз пять раз"></textarea>
      <div class="bp-row"><button class="sm primary" id="draftBtn" onclick="draftMake()">Составить шаги</button></div>
      <div id="draftOut"></div>`;
    $('mActs').innerHTML = `${toolsBackButton()}<span class="sp"></span><button onclick="closeModal()">Закрыть</button>`;
    modalSheet('wide');
    openModal();
}

async function draftMake() {
    const out = $('draftOut');
    const serial = $('draftPhone').value, task = $('draftTask').value.trim();
    if (!serial) return toast('нет телефона в сети', 'bad');
    if (!task) return toast('опишите задачу', 'bad');
    $('draftBtn').disabled = true;
    out.textContent = 'Думаю…';
    try {
        DRAFT = await api('/api/vlm/plan', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({serial, task})});
        out.innerHTML = `<ol>${DRAFT.steps.map(s => `<li>${esc(draftStepText(s))}</li>`).join('')}</ol>
          <div class="bp-row"><button class="sm primary" onclick="draftSave()">Сохранить как сценарий</button></div>
          <small class="dim">Это черновик. Откройте его в конструкторе, проверьте и запустите на одном телефоне.</small>`;
    } catch (e) {
        DRAFT = null;
        out.textContent = e.message;
    }
    $('draftBtn').disabled = false;
}

async function draftSave() {
    if (!DRAFT) return;
    try {
        const res = await api('/api/recorder/save', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(DRAFT.recipe)});
        toast(`Сохранено: ${DRAFT.recipe.meta.name}. Найдите его на вкладке «Сценарии».`, 'ok');
        DRAFT = null;
        await loadScenarios(true);
        return res;
    } catch (e) {
        toast(e.message, 'bad');
    }
}

toolsRegister({id: 'draft', icon: 'record', title: 'Черновик по описанию',
               sub: 'нейросеть предложит шаги, вы проверите', open: draftOpen});
```

`frontend/index.html`: после `tool-api.js` добавить `<script src="js/tool-draft.js"></script>`.

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && python -m pytest tests/test_vlm_plan.py tests/test_tools_js.py -q`
Expected: all PASS.

```bash
git add backend/farm/vlm/plan.py backend/farm/api/vlm.py frontend/js/tool-draft.js frontend/index.html backend/tests/test_vlm_plan.py
git commit -m "F9: черновик сценария по описанию словами"
```

---

### Task 12: документация и сверка

**Files:**
- Modify: `README.md`, `docs/guide.md`, `.claude/skills/farm-ux/SKILL.md`, `docs/superpowers/specs/2026-10-25-ready-stories-design.md` (раздел отступлений)

- [ ] **Step 1: Edit docs**

`README.md`: в таблицу «Что умеет» добавить строку:

```
| **Инструменты** — здоровье телефонов (память, процессор, нагрев), уведомления, резервная копия, API, черновик по описанию | **Массовые** — «Разрешение» (одинаковое на всех), «Каждому своё» (строка файла — телефону), «Контакты», F1–F9 для быстрых фраз |
```

`docs/guide.md`: добавить раздел «Инструменты и массовые функции» с подразделами: Разрешение; Каждому своё (режимы, разделитель, шаблон `{1}@mail.ru`); Горячие клавиши F1–F9; Здоровье; Уведомления (только шторка; тексты банков не показываются); Резервная копия (ключ adb — по галке, где лежат прежние файлы после восстановления); Контакты (не все прошивки дают писать); Черновик по описанию (нужен включённый помощник, результат — обычный сценарий-черновик). Ссылка на `docs/public-api.md`.

`.claude/skills/farm-ux/SKILL.md`, в «LaiXi parity checklist» перед строкой `Added 2026-10-25: «Готовые» сюжеты` добавить:

```
Added 2026-10-25: окно «Инструменты» (кнопка в шапке, `tools.js`): здоровье телефонов (RAM/ROM/CPU в опросе реестра, тревоги в «Требуют внимания»), уведомления, резервная копия (`backup.py`), «Для программистов» (`docs/public-api.md`), черновик по описанию (`vlm/plan.py`); массовые «Разрешение», «Каждому своё», «Контакты»; F1–F9 для быстрых фраз. Не берём: рассылки, P2P, хаб AndroidsBox.
```

Спека `docs/superpowers/specs/2026-10-25-ready-stories-design.md`, в конец «Часть 2» добавить подраздел «Отступления, найденные при реализации» с четырьмя пунктами из «Global Constraints» этого плана (F3, F7, F8, F2).

- [ ] **Step 2: Run the whole suite**

Run: `cd backend && python -m pytest -q`
Expected: все тесты PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/guide.md .claude/skills/farm-ux/SKILL.md docs/superpowers/specs/2026-10-25-ready-stories-design.md
git commit -m "Документация: инструменты, массовые функции и отступления от спеки"
```

---

## Self-Review

**Spec coverage (часть 2):** F1 — T1, T2; F2 — T7; F3 — T6; F4 — T3; F5 — T8; F6 — T9; F7 — T10 (с обоснованным отступлением: токен и 101 маршрут уже есть); F8 — T4; F9 — T11; общее окно — T5; документация — T12. Первая волна (F1, F2, F3, F4, F8) — T1–T7 по порядку, вторая (F5, F6, F7) — T8–T10, последняя (F9) — T11.

**Отступления от спеки и почему:** F3 без отдельного эндпоинта (данные уже едут с `/api/devices`); F7 без второго токена (есть `FARM_TOKEN`); F8 только в окне массовых действий; F2 экспорт через `POST`. Все четыре записаны в T12 и в начале плана.

**Placeholder scan:** заглушек нет. Две оговорки исполнителю — в T10 (если поля задачи в примере Python называются иначе, поправить пример по живой ферме) и T6 (существующий тест реестра может сверять точный набор ключей) — с указанием, что делать.

**Type consistency:** `display.*` (T1) ↔ `screen._resolution_*`, `bulk._display_info` (T2); `lines.assign/render/split_row/clean_rows` (T3) совпадают с эндпоинтом и тестами; `health.read` ↔ `Registry._read_health` ↔ `Device.ram_free/rom_used/cpu` ↔ JS `healthRows` (T6); `backup.build/inspect/restore` ↔ `api.backup.export_backup/inspect_backup/restore_backup` (T7); `notifications.scan_phone(serial, packages, show_text)` ↔ `api.notifications.scan` (T8); `contacts.generate/insert_scripts/check_output/CLEAR_SCRIPT` ↔ `screen._contacts_*` (T9); `plan.plan/recipe_for/PlanError` ↔ `api.vlm.make_plan` (T11); `toolsRegister/toolsBackButton` (T5) используют T6–T11.
