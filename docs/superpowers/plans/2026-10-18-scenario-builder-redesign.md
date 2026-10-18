# Конструктор «Список-фразы» — план

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** разгрузить конструктор сюжетов по спеке `docs/superpowers/specs/2026-10-18-scenario-builder-redesign-design.md`.

**Architecture:** только фронтенд. Формат recipe не трогаем. Схема остаётся в коде, но скрыта; список шагов — единственный вид. Новый чистый модуль `stepfail.js` держит маппинг «Если не нашёл» ↔ `optional`/`retries`.

**Tech Stack:** vanilla JS (глобальные функции, inline onclick), CSS, `strings/ru.json` + `t()`; JS-тесты через node из pytest (`backend/tests/_node.py`).

## Global Constraints
- Новые тексты интерфейса — только через `strings/ru.json` (`t()` / `data-t`), без русских литералов в JS.
- Формат сюжета не меняется; старые сюжеты открываются.
- Сохранить все возможности: запись после, проверить шаг, запустить отсюда, дублировать, выше/ниже, удалить, выделение, код, изменения, якорь, развилка, помехи.

---

### Task 1: «Если не нашёл» — чистый модуль + тест
**Files:** Create `frontend/js/stepfail.js`, `backend/tests/test_stepfail_js.py`; Modify `frontend/index.html` (script перед steptools.js), `frontend/js/steptools.js:235-257` (`recBadges`, `recFlexEditor`), `frontend/strings/ru.json`.

**Interfaces — Produces:**
- `stFailGet(step) -> {tries: 1..6, skip: bool}` (`tries = retries + 1`).
- `stFailSet(step, {tries, skip})` — мутирует `step.retries = clamp(tries-1, 0, 5)`, `step.optional = !!skip`; ноль/false удаляют поле.
- `ST_FAIL_TRIES = [1, 2, 3, 4, 6]`.

- [ ] Тест в node: `stFailGet({})` → `{tries:1, skip:false}`; `stFailSet(s,{tries:3,skip:true})` → `retries 2, optional true`; `tries:1, skip:false` удаляет оба поля; `tries:99` → `retries 5`.
- [ ] Запустить — FAIL (нет файла).
- [ ] Написать `stepfail.js`, подключить в index.html.
- [ ] `recFlexEditor` → блок «Если не нашёл»: `Пробовать [select ST_FAIL_TRIES] раз, потом [Остановить и показать ошибку | Пропустить и идти дальше]`, `onchange → recSetFail(id, field, value)`; `recBadges` — один значок «не нашёл → пропустит» / «×N», тексты из ru.json.
- [ ] pytest зелёный; commit.

### Task 2: Строка шага — ▶ и ⋯
**Files:** Modify `frontend/js/recorder.js:2149-2215` (`recRow`, `recDelete`), `frontend/css/recorder.css`, `frontend/strings/ru.json`.
- [ ] В `.rs-acts` оставить `▶ Проверить шаг` (`recRunStep(index)`) и кнопку `⋯` → `recRowMenu(ev, id, index)`.
- [ ] `recRowMenu` рисует абсолютное меню `.rs-menu` (Записать после, Запустить отсюда, Дублировать, Выше, Ниже, Удалить), закрывается кликом вне / Esc.
- [ ] Галочка `.rs-sel` и ручка видны при наведении/фокусе или когда `REC.sel.size` (класс `has-sel` на `#recSteps`).
- [ ] `recDelete` → `toast(t('rec.shag_udalen'), '', {label: t('rec.vernut'), onClick: recUndo})`.
- [ ] Все `title` — через `t()`. Проверка в браузере; commit.

### Task 3: Раскрытый шаг — главное + «Дополнительно»
**Files:** Modify `frontend/js/recorder.js` (`recRow` хвост), `frontend/css/recorder.css`.
- [ ] Видно сразу: `recThumb`, `recValueEditor`, `recBlockEditor`, `recFlexEditor` (Если не нашёл).
- [ ] `<details class="rs-more"><summary>Дополнительно</summary>` — `rs-code`, `recAlts`, `recAnchorEditor`, `recBranchEditor`. Открыт, если в нём уже что-то настроено (`step.anchor`/развилка).
- [ ] Проверка в браузере; commit.

### Task 4: Верхняя панель — 5 кнопок + ⋯
**Files:** Modify `frontend/index.html:316-420,424-456`, `frontend/js/recorder.js` (`REC.view`, `recSetView`, `recSchemeRefresh`), `frontend/css/recorder.css`.
- [ ] Удалить `#recViewToggle`; `REC.view = 'list'`; `#recScheme hidden`, `#recSteps` видим.
- [ ] Второй ряд: `+ Добавить шаг` (`recLibOpen`), Отменить/Вернуть, `⋯ Ещё` (`<details class="recmore">`): Проверка экрана, Если на экране…, Изменения, Код, Если выскочило окно (открывает `#recSide`), галочки паузы/сверять экран.
- [ ] `#recSide` вынести под `#recSteps`; `recSchemeRefresh` грузит сторону, если `#recSide` существует (не по `REC.view`).
- [ ] Проверка: старт записи, кнопки работают; commit.

### Task 5: Простые слова
**Files:** `frontend/strings/ru.json`.
- [ ] Заменить значения ключей: `device.razvilka` «Если на экране…», `device.proverka_ekrana` «Убедиться, что экран тот», `device.avto_proverki` «сверять экран сам», `device.vsplyvayuschie_okna_i_pomehi` «Если выскочило окно», `rec.krugov` «попыток», `rec.chto_ischem` «Что должно быть на экране», `rec.feat_id` «технический код кнопки», `rec.dobavit_inache` «+ Если нет — то…», `rec.on_fail_skip` «пропустить и идти дальше», `rec.on_fail_stop` «остановить и показать ошибку», `rec.blok_povtor` «повторять», `rec.blok_shans` «иногда» (только существующие ключи).
- [ ] JSON валиден; commit.

### Task 6: Проверка целиком
- [ ] `cd backend && ../.venv/bin/pytest -q` — зелёный.
- [ ] `./run.sh`, браузер :8777 → устройство → конструктор: скриншоты, клики по ⋯, правка шага, «Если не нашёл», блок, удаление+Вернуть, консоль без ошибок.
