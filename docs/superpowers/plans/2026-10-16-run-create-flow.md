# Сквозной путь «создал → запустил → разобрался» — план

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.
> Исполняется inline в той же сессии. Коммиты — только по команде пользователя (в шагах их нет намеренно).

**Goal:** одно окно запуска с проверкой готовности телефонов, связанные переходы между разделами, без дублей кода.

**Architecture:** сервер отдаёт `needs_accounts` у сценария, `accounts` у телефона, `POST /api/run/preflight` и `batch` у задач. Фронт: `rundialog.js` — единственная точка запуска на ферме; общие помощники в `core.js`.

**Tech Stack:** FastAPI, ванильный JS без сборки, pytest.

Spec: `docs/superpowers/specs/2026-10-16-run-create-flow-design.md`.

## Global Constraints
- Платформы ровно `vk, inst, tiktok, tg` (`farm/accounts.py:PLATFORMS`).
- Логины/пароли никогда не уходят в `/api/devices` и preflight — только `platform` и `status`.
- Токены цвета из `base.css`; цвет не единственный признак.
- Тексты по-русски, тосты строчными.
- Проверка: pytest один раз в конце + один проход браузера на моках; localStorage пользователя не чистить.

---

### Task 1: Общие помощники `armConfirm`, `store`, `emptyState`

**Files:** Modify `static/js/core.js`, `static/js/bulk.js`, `static/js/accounts.js`, `static/js/fleet.js`.

**Produces:**
- `armConfirm(btn: HTMLElement, armedText: string) -> boolean` — true на втором нажатии в течение 4 с.
- `store.get(key: string, fallback: any) -> any`, `store.set(key: string, value: any) -> void`.
- `emptyState({art?: string, title: string, text: string, action?: string}) -> string` (HTML).

- [ ] Добавить в `core.js`:
```js
const store = window.store = {
    get(key, fallback) {
        try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); }
        catch (e) { return fallback; }
    },
    set(key, value) {
        try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* приватный режим */ }
    },
};

function armConfirm(btn, armedText) {
    if (btn.dataset.armed) return true;
    btn.dataset.armed = '1';
    btn.classList.add('armed');
    const label = btn.querySelector('span') || btn;
    btn.dataset.label = label.textContent;
    label.textContent = armedText;
    setTimeout(() => {
        delete btn.dataset.armed;
        btn.classList.remove('armed');
        label.textContent = btn.dataset.label;
    }, 4000);
    return false;
}

function emptyState({art, title, text, action}) {
    return `<div class="emptybig">${art ? emptyArtHtml(art) : ''}
      <h3>${esc(title)}</h3><p>${esc(text)}</p>${action || ''}</div>`;
}
```
(`emptyArtHtml` — существующий рисовальщик пустых состояний из `core.js`; если имя иное — использовать существующее.)
- [ ] Заменить: `bulk.js` `confirmInline`/`bulkClearData` и `accounts.js` `accDelete` → `armConfirm`; `loadPref/savePref` в `bulk.js` и `DENSITY_KEY` в `fleet.js` → `store`; пустое состояние «Аккаунтов» → `emptyState`.
- [ ] `node --check` на изменённые файлы.

### Task 2: Сервер — `needs_accounts`, `accounts` у телефона, preflight, batch

**Files:** Modify `farm/scenarios.py`, `farm/api/scenarios.py`, `farm/devices/registry.py`, `farm/accounts.py`, `farm/devices/runner.py`. Test: `tests/test_run_preflight.py`.

**Produces:**
- `scenarios.needs_accounts(source: str) -> list[str]` (sorted, только PLATFORMS).
- `Scenario.needs_accounts: list[str]` + в `to_dict`.
- `accounts.summary_for(serial) -> list[{"platform","status"}]`; `Device.to_dict()["accounts"]`.
- `scenarios.preflight(sc, serials) -> {"counts": {status: n}, "devices": {serial: {"status", "platform"?}}}`; статусы `ready|offline|busy|no_account|banned|login`.
- `POST /api/run/preflight {scenario, serials}`.
- `Job.batch: str`, `runner.submit(..., batch=None)` — один id на вызов; `/api/run` возвращает `batch`.

- [ ] Тест:
```python
import types
from farm import scenarios, accounts
from farm.devices import runner

def test_needs_accounts_literals_only():
    src = 'def run(ctx):\n ctx.account("vk")\n ctx.account("tg")["login"]\n ctx.account(p)\n ctx.account("fb")\n'
    assert scenarios.needs_accounts(src) == ["tg", "vk"]

def test_needs_accounts_none():
    assert scenarios.needs_accounts("def run(ctx):\n pass\n") == []

def _dev(serial, online=True, busy=None):
    return types.SimpleNamespace(serial=serial, online=online, busy_job=busy)

def test_preflight_statuses(monkeypatch):
    devs = {"a": _dev("a"), "b": _dev("b", online=False), "c": _dev("c", busy="j"),
            "d": _dev("d"), "e": _dev("e"), "f": _dev("f")}
    monkeypatch.setattr(scenarios.registry, "get", devs.get)
    accs = {"a": {"status": "active"}, "c": {"status": "active"},
            "e": {"status": "banned"}, "f": {"status": "login"}}
    monkeypatch.setattr(accounts, "for_device", lambda s, p=None: accs.get(s))
    sc = types.SimpleNamespace(needs_accounts=["vk"])
    out = scenarios.preflight(sc, list(devs))
    st = {k: v["status"] for k, v in out["devices"].items()}
    assert st == {"a": "ready", "b": "offline", "c": "busy", "d": "no_account",
                  "e": "banned", "f": "login"}
    assert out["counts"]["ready"] == 1

def test_preflight_without_accounts_needed(monkeypatch):
    monkeypatch.setattr(scenarios.registry, "get", lambda s: _dev(s))
    out = scenarios.preflight(types.SimpleNamespace(needs_accounts=[]), ["x"])
    assert out["devices"]["x"]["status"] == "ready"
```
- [ ] Запустить — FAIL (нет функций).
- [ ] Реализовать `needs_accounts` через `ast.walk`: `Call` с `func.attr == "account"`, первый аргумент `ast.Constant(str)` из `accounts.PLATFORMS`. Вызывать в `_load` из прочитанного исходника.
- [ ] Реализовать `preflight` (порядок проверок: offline → busy → для каждой платформы аккаунт: нет → no_account, banned → banned, login → login; иначе ready).
- [ ] `accounts.summary_for`, `Device.to_dict` поле `accounts`; `Job.batch`, `submit(batch)`, `to_dict["batch"]`; эндпоинт preflight; `/api/run` → `{"jobs", "batch"}`.
- [ ] pytest файла — PASS.

### Task 3: Окно запуска `openRunDialog` + сводка

**Files:** Create `static/js/rundialog.js`; Modify `static/index.html` (runbar, script tag), `static/js/scenarios.js` (`scRunBarHtml` → кнопка), `static/js/bulk.js` (`groupRunMenu` → `openRunDialog({mode:'groups'})`), `static/js/fleet.js` (`renderRunbar` без select), `static/css/bulk.css`.

**Interfaces:** Consumes `store`, `/api/run/preflight`, `/api/accounts/autobind`, `paramField`, `collectParams`-подобный сбор по `#rd_<name>`. Produces `openRunDialog({scenario?, serials?, mode?: 'devices'|'groups'})`, `RUN.last` (последний сценарий в `store` `farm.run.last`).

- [ ] Окно: select сценария → параметры → «Кто»: «Выбранные (N)» / группа из списка / «Все в сети» → «Повторов» → сводка → «Запустить на K».
- [ ] Сводка перезапрашивается при смене сценария/«Кто» (debounce 150 мс): строка счётчиков + список проблемных телефонов (имя · причина), кнопка «Раздать аккаунты <платформа>» при `no_account`.
- [ ] Запуск: только `ready|busy|login`; `POST /api/run` → `showRuns(batch)` (Task 4).
- [ ] Режим «По группам»: таблица группа → сценарий, общий «Повторов»; каждая группа своим `/api/run`, один общий `batch` не нужен — переход в «Все запуски».
- [ ] Удалить старые: select/«Повторов» из `#runbar` (оставить «Действия», «Запустить…»), `scRunBarHtml` → кнопка «Запустить…», `groupRunGo`.

### Task 4: Стыки — фильтр по запуску, «Запустить на ферме», «Починить шаг»

**Files:** Modify `static/js/jobs.js`, `static/js/recorder.js` (после сохранения), `static/js/deviations.js` (вынести кнопку), `static/index.html`.

**Produces:** `showRuns(batch?: string)`; `repairButtonHtml(item)`.

- [ ] `S.runBatch`; `pollJobs`-рендер фильтрует по `batch`; над списком полоса «<сценарий> на N: X готово · Y сбой · Z в работе» + «Показать все запуски».
- [ ] После успешного сохранения сценария: `toast('сохранено', 'ok', {label: 'Запустить на ферме', run: () => openRunDialog({scenario: key})})` — формат действия как у существующего `toast(message, kind, action)`.
- [ ] В журнале упавшей задачи — «Починить шаг» через общий `repairButtonHtml`, если у задачи есть соответствующее отклонение.

### Task 5: Значок аккаунта на плитке, карточка сценария, фокус

**Files:** Modify `static/js/fleet.js` (`tileUpdate`), `static/js/scenarios.js` (карточка), `static/css/bulk.css`.

- [ ] Плитка: при `accounts` со `banned` — красная точка «бан <платформа>», с `login` — жёлтая «нужен вход»; текст в `title` и видимая иконка.
- [ ] Карточка сценария: строка «нужен аккаунт: VK, TG» и «последний: 38 ок · 2 сбоя» (поля `needs_accounts`, `passed`, `failed`).
- [ ] `:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }` для новых классов: `.bulk-grid button, .seg button, .live-switch, .phone-pick button, .gr-try, .acc-table input, .acc-table select, .rd *`.

### Task 6: Проверка

- [ ] `node --check` всех изменённых JS; `.venv/bin/python -m pytest -q` — всё зелёное.
- [ ] Браузер, один проход на моках (fetch-стаб `/api/devices`, `/api/run/preflight` — реальный сервер): ферма → выбрать 5 → «Запустить…» → сводка; «Сценарии» → карточка; «Запуски» с фильтром. Скриншоты сохранить.
- [ ] Дописать в навык `farm-ux`: «запуск только через openRunDialog», помощники `armConfirm/store/emptyState`.
