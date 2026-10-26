# Шаги сюжетов, группы фраз и ИИ-агент — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax. Unlike the earlier plans, this one describes behaviour, interfaces and acceptance criteria instead of verbatim code: the UI parts are design-heavy and the implementer is expected to read neighbouring code and match it. Pure logic is still test-first.

**Goal:** (A) Добавленный из галереи сюжет можно смотреть и править по шагам; (B) группы быстрых фраз на сервере; (C) пошаговый ИИ-агент на одном телефоне. Интерфейс везде заметно лучше обычного.

**Spec:** `docs/superpowers/specs/2026-10-26-steps-phrases-agent-design.md` — главный источник требований и UX-деталей. Читать целиком перед началом любой задачи.

**Tech Stack:** Python 3.9+, FastAPI (роутеры в тестах зовутся как функции), pytest, чистый JS без сборки, Node для JS-тестов.

## Global Constraints

- Python `>=3.9`: `X | None` в аннотациях только с `from __future__ import annotations`; без `match`.
- Чистые модули без adb, диска и FastAPI; случайное через параметр `rng`.
- Интерфейс: правила из спеки («Общие правила интерфейса») и из `.claude/skills/farm-ux/SKILL.md` (прочитать). Только токены `frontend/design/tokens.css`; **новые строки интерфейса — в `frontend/strings/ru.json`** через `data-t`/`t()`; слова «телефон», «запуск»; один основной (`.primary`) ярлык на панель; разрушающее действие через `armConfirm`; пустые состояния через `emptyBig`; `modalSheet(...)` перед `openModal()`; состояния загрузка/ошибка/пусто/успех всегда явные.
- JS-тесты: `esc`-заглушка должна экранировать `>`; `assert.deepStrictEqual` на объектах из `vm` требует `JSON.parse(JSON.stringify(...))`.
- Тесты не требуют телефона и не трогают настоящие `data/`, `~/.android`; запуск из `backend/`: `python -m pytest tests/<файл> -q`; интерпретатор с зависимостями `/Users/hlamov.ilya/Desktop/android-farm_final/.venv/bin/python`.
- Перед коммитом один раз полный прогон `pytest -q`; он зелёный (на старте 1761 прошёл).
- Работа в git worktree `/Users/hlamov.ilya/Desktop/android-farm_laixi`, ветка `feature/steps-phrases-agent`. Основную папку `/Users/hlamov.ilya/Desktop/android-farm_final` не трогать. `git add` только по именам файлов; в конец сообщения коммита пустая строка и `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Не пушить.
- Проверка визуала на ширинах 1280 и 1728: по возможности через `node --check` и логику; браузерная проверка один раз в самом конце всей работы (контроллер).

---

### Task 1: `steps_text.py` — шаги словами

**Files:** Create `backend/farm/steps_text.py`, `backend/tests/test_steps_text.py`.

**Interfaces — produces:** `describe(steps: list[dict]) -> list[dict]`, элемент `{"text": str, "depth": int}`; `depth` — вложенность блоков (`loop`, `chance`, `until`, `if_seen`, `if_phone`: шаги внутри на уровень глубже, считать по `args.span`). Рецептные шаги: `{"kind", "args", "selector"?, "any"?, "note"?}` (формат — `docs/recipe-format.md`, схема — `farm.recorder.steps.schema()`).

**Требования:** человеческие фразы по видам шагов из спеки A2: `launch_app` «Открыть приложение» (если в args есть `package` — известное имя через `farm.control.apps`/`apklib.name_of` не нужно; можно «Открыть приложение <пакет>» только если пакет не угадывается, но лучше «Открыть приложение»), `loop` («Повторять N раз» / «Повторять N минут»), `chance` («С шансом N%:»), `sleep` («Пауза 6–14 с» при `seconds_max`, иначе «Пауза 3 с»), `swipe` («Провести вверх/вниз/влево/вправо» по координатам), `click` (если есть `note` — взять её; иначе «Нажать» + текст/описание из `selector.args`, если это `text="…"`/`description="…"`, иначе «Нажать на элемент»), `type` («Ввести текст»; с `account` — «Ввести <поле> из аккаунта телефона»), `key`, `tap`, `budget` («Потолок за сутки: <имя> — <лимит>»), `wait`, `if_seen` («Если на экране есть …»), `ensure_app`, `open_url`, `stop_app`, `finish`, `break` и остальные из схемы. Неизвестный вид — «Шаг: <вид>». Никаких классов, id и координат в тексте. Заголовок блока идёт отдельной строкой, шаги внутри — на `depth+1`.
**Тесты:** по строке на вид шага; вложенность (loop → chance → click даёт depth 0,1,2); неизвестный вид; пустой список; `span`, выходящий за конец списка, не роняет (клампится).

- [ ] Написать тесты → увидеть падение → реализовать → зелёный → коммит («Шаги словами: steps_text.describe»).

---

### Task 2: галерея читает рецепты и показывает шаги

**Files:** Modify `backend/farm/gallery.py`, `backend/farm/api/gallery.py` (если нужны правки), `backend/tests/test_gallery.py`.

**Interfaces — consumes:** `steps_text.describe`, `farm.recorder.save.save(key, meta, params, steps, overwrite=False)` (бросает `Conflict`/`SaveError`; нормализацию делает `farm.recorder.steps.normalize_meta/normalize_params/normalize_steps`, как в `api/recorder.py::_parse`), `farm.scenarios.discover`.
**Produces:** `gallery.items()` каждый элемент дополнительно: `kind` (`"recipe"|"code"`), `editable` (bool), `steps_text` (список `{"text","depth"}`), `params` (список `{"name","label"}` — метки полей формы, для предпросмотра). Для `.py` — `steps_text` из `STEPS` (список строк, depth 0; через `ast.literal_eval`, без выполнения), `editable=False`. Для `<ключ>.recipe.json` — поля из файла (`gallery.platform/verified/package`, `meta.name/description`), `steps_text=describe(steps)`, `editable=True`. `gallery.add(key)` для рецепта сохраняет через saver под уникальным ключом (`_2`…), для кода копирует файл, как раньше; возвращает ключ копии. Ключи `.recipe.json` проверяются тем же `KEY_RE`; файл рецепта не должен попадать в `scenarios.discover()` (он вне `scenarios/*.py`).
**Требования:** битый JSON или рецепт, не прошедший нормализацию, — карточка пропускается с предупреждением в журнал, остальные видны. `added` для рецепта — по наличию сценария с ключом `key` или `key_N`. Старые тесты галереи остаются зелёными (дополнить).
**Тесты:** карточка рецепта (steps_text, editable, params), добавление рецепта создаёт записанный сценарий, который `scenarios.is_recorded` и `saver.load_recipe` видят; повторное добавление `_2`; кодовая карточка с `STEPS`; битый рецепт пропущен; рецепт не виден в `discover`.

- [ ] Тесты → реализация → полный прогон → коммит («Галерея: рецепты, шаги словами, editable»).

---

### Task 3: сюжеты-рецепты и описание шагов у кодовых

**Files:** Create `backend/scenarios/gallery/shorts_autoscroll.recipe.json`, `vk_feed.recipe.json`, `youtube_shorts.recipe.json`, `spotify_one.recipe.json`, `telegram_one.recipe.json`. Delete `shorts_autoscroll.py`, `vk_feed.py`, `youtube_shorts.py`. Modify `tiktok_feed.py`, `spotify_listener.py`, `telegram_channels.py` (добавить `STEPS`, у двух последних поменять `NAME` на «… (по списку)»). Modify `backend/tests/test_gallery_scenarios.py` (под новые файлы). Modify `.gitignore` только если рецепт-файлы игнорируются (проверить `git check-ignore`).

**Требования:**
- Рецепты собрать по `docs/recipe-format.md`; `meta`: `name`, `description`, `watch_popups: true`, `human: true`; `gallery`: `platform`, `verified: false`, `package`. Параметры формы (`params`) — только те, что нужны (приложение, число повторов/минут, пауза); подстановка параметров в шаги — только если схема это допускает (`schema.parametrizable`), иначе значения прямо в шагах.
  - Автолистание: запуск приложения, `loop` (times 50, pause 1–3), внутри свайп вверх и пауза `sleep 7–20` (seconds/seconds_max).
  - VK: `loop` (40), свайп, пауза 3–8, `chance` 20% → `budget` (лайки, 200, `vk`) + `click` с `resourceId=".../iv_likes"` и запасным слоем `point`.
  - YouTube Shorts: запуск, `if_seen`/`click` на вкладку Shorts (опционально через `optional: true`), `loop` (40), свайп, пауза 6–14, `chance` 20% → `budget` + `click` по `descriptionMatches` лайка.
  - Spotify (одно слово): запуск, нажатия по `resourceId` из `spotify_listener.py` (`search_tab`, `find_search_field`), `type` слова (параметр), нажатие по первому результату (точка-запасной вариант), `budget` + `chance` лайк, пауза 30–90 с.
  - Telegram (один канал): запуск, поиск, `type` названия, `click` по тексту, `loop` (8) со свайпом вниз и паузой, `key back` ×3.
- Для кодовых: `STEPS` — список строк простыми словами (6–12 пунктов), отражающих реальное поведение файла (читать код).
- Обновить `test_gallery_scenarios.py`: ключи файлов; для каждого рецепта — `normalize_meta/params/steps` проходят, `codegen.render` собирается, `recorder.validate.validate(...)` без ошибок (предупреждения допустимы); для кодовых — метаданные, `STEPS` непустой; для всех — `describe` не падает.
- Если какой-то рецепт не проходит валидацию и поправить нельзя без потери смысла — оставить для него код-версию, сообщить в отчёте.

- [ ] Тест (обновить) → рецепты/правки → полный прогон → коммит («Сюжеты: рецепты вместо кода, шаги у кодовых»).

---

### Task 4: «Сценарии» — блок «Что делает»

**Files:** Modify `backend/farm/scenarios.py` (`Scenario.steps_text`, `to_dict`), `backend/farm/api/scenarios.py` (для рецептов — `steps_text` из `steps_text.describe(recipe["steps"])`), `frontend/js/scenarios.js`, `frontend/css/*.css` (подходящий файл), `frontend/strings/ru.json`, тесты.
**Требования:** `Scenario.steps_text` — из `STEPS` модуля (`list[str]`) → `[{"text","depth":0}]`, иначе `[]`. В списке `GET /api/scenarios` у каждого элемента поле `steps_text` (для рецептов — из рецепта). В панели выбранного сценария (рядом с блоком «шаги»/параметрами; изучить `renderParams`/`scSteps` в `scenarios.js`) — сворачиваемый блок «Что делает» с нумерованным списком и отступами по `depth`; у кодового сценария подпись «Правится только через параметры формы»; у рецепта — кнопка «Открыть в конструкторе» (вызов уже существующего открытия на правку; найти). Состояние раскрытия запоминается (`store`). Чистая функция `scStepsListHtml(items)` с JS-тестом (экранирование, глубина, пусто).
- [ ] Тесты → реализация → полный прогон → коммит («Сценарии: блок «Что делает»»).

---

### Task 5: интерфейс галереи

**Files:** Modify `frontend/js/gallery.js`, `frontend/css/gallery.css`, `frontend/strings/ru.json`, `frontend/index.html` (шапка вкладки: поиск и чипы), `backend/tests/test_gallery_js.py` (обновить).
**Требования (спека A5):** шапка (поиск + чипы платформ + счётчик), карточки с плиткой платформы (цвет — токены; буква/значок), бейджи («Правится в конструкторе» зелёный, «Только параметры» серый, «Не проверено на телефоне» янтарный), сворачиваемый список «Что делает» (кнопка-заголовок с `aria-expanded`, номера, отступы по depth), «Добавить в мои» — единственный основной ярлык карточки; после добавления тост с кнопкой «Открыть» (рецепт → конструктор через уже существующую функцию правки сценария; код → выбрать сценарий в «Сценариях») и карточка «Уже в моих · Открыть». Клавиатура: стрелки между карточками, `Enter`/`Space` раскрыть, `A` добавить; подсказка клавиш мелким текстом. Поиск и фильтр без мигания; чистые функции `galleryFilter(items, query, platform)`, `galleryPlatforms(items)`, `galleryCard(item)` — с JS-тестами. Скелетон при загрузке, ошибка с «Повторить». Не ломать `GALLERY`/`galleryShow`/`galleryAdd`/`galleryCard` (index.html и app.js вызывают).
- [ ] Тесты → реализация → полный прогон → коммит («Галерея: поиск, фильтры, шаги, открыть после добавления»).

---

### Task 6: `phrase_store.py` и API фраз

**Files:** Create `backend/farm/phrase_store.py`, `backend/farm/api/phrases.py`, `backend/tests/test_phrase_store.py`. Modify `backend/farm/api/__init__.py`, `backend/farm/config.py` (`PHRASES_FILE`), `backend/farm/backup.py` (EXTRA_DATA += `"phrases.json"`) и его тест.
**Interfaces — produces:** `phrase_store.load() -> dict`, `save(data) -> dict` (очистка и лимиты: ≤30 групп, ≤100 фраз, фраза ≤500 символов, имя группы ≤40; пустые фразы и дубли внутри группы выбрасываются; id группы — короткий случайный; всегда есть хотя бы одна группа «Общие»; `active` существует), `import_text(data, group_id, text) -> dict` (по строке на фразу, `.csv` с `;`/`,` — берётся первый столбец), `export_csv(data, group_id) -> bytes` (UTF-8 BOM). API: `GET /api/phrases`, `PUT /api/phrases`, `POST /api/phrases/import`, `GET /api/phrases/export?group=`. Файл читается/пишется атомарно (`os.replace`); битый файл → значения по умолчанию, а не падение.
**Тесты:** лимиты, очистка, дубли, активная группа, импорт txt/csv, экспорт, битый файл, атомарность записи, API-функции, бэкап включает `phrases.json`.
- [ ] Тесты → реализация → полный прогон → коммит («Группы фраз: хранение и API»).

---

### Task 7: интерфейс групп фраз

**Files:** Modify `frontend/js/bulk.js` (убрать `phrases()` из `localStorage`; панель `text`; `phrasesHtml`; обработчик F1–F9; `phraseSave`/`phraseDrop`), `frontend/css/bulk.css` (стили групп), `frontend/strings/ru.json`, `backend/tests/test_phrase_hotkeys_js.py` и связанные.
**Требования (спека B2–B3):** вкладки групп с «+», переименование (двойной клик/`F2`), удаление через `armConfirm`, плашки фраз с `F1–F9`, строка «Добавить фразу» (`Enter`), подсказка «вариантов: N» (использовать `phrCount` из `phrases.js`), импорт/экспорт, переезд из `localStorage` (`farm.phrases`) один раз, после успеха ключ удаляется по точному имени. Состояние групп — в памяти + `PUT /api/phrases` с отложенной записью (debounce) и откатом при ошибке с тостом. F1–F9 по активной группе, подсказка с названием группы. Чистые функции (разбор, `phraseForHotkey(ev, list)` остаётся) с JS-тестами; не ломать другие вызовы `phrases()` (grep по всему `frontend/js`).
- [ ] Тесты → реализация → полный прогон → коммит («Группы фраз: вкладки, горячие клавиши, импорт и экспорт»).

---

### Task 8: `vlm/agent.py` и API агента

**Files:** Create `backend/farm/vlm/agent.py`, `backend/tests/test_vlm_agent.py`. Modify `backend/farm/api/vlm.py`, `backend/farm/config.py` (`AGENT_MAX_STEPS` env `FARM_AGENT_MAX_STEPS`, по умолчанию 30), при необходимости `backend/farm/vlm/client.py`.
**Interfaces — consumes:** то же, что `backend/farm/vlm/plan.py` (изучить: `settings.get()`, `usage.reserve/refund`, `loc.safety.secret_goal`, `loc.safety.secret_screen(nodes)`, `loc.screen_gate`, `client.ask(image, prompt, cfg=None, max_tokens=...)`, `control.screenshot`, дамп иерархии как в `plan.py`), `screen.ACTIONS` для исполнения.
**Produces:** `agent.step(serial, task, history) -> dict` с одним из: `{"action": {...}, "why": str}`, `{"done": true, "why": str}`, `{"ask": true, "why": str}`; `history` — список выполненных `{"action","why","result"}` (последние N в запрос). `agent.validate_action(action) -> dict` — разрешены: `tap{x,y}`, `swipe{x1,y1,x2,y2}`, `type{value}`, `key{name}` (белый список клавиш: back, home, enter, recents, delete), `launch_app{package}`, `open_url{url}` (только http/https), `wait{seconds≤10}`; координаты в [0,1]; текст ≤500; секрет в `type.value` → отказ; всё прочее отбрасывается с `AgentError`. `agent.is_loop(history, action)` — два одинаковых действия подряд без смены экрана (сравнивать по хэшу кадра, который клиент/сервер передаёт, либо по равенству действия трижды подряд — реализовать проще вторым). `agent.do(serial, action) -> dict` валидирует и исполняет через `screen.ACTIONS` (маппинг `launch_app`→`launch`, `type`→`text`, `open_url`→`url`, `wait`→ пауза на сервере), возвращает `{"ok": True}`. `agent.recipe(task, history) -> dict` — рецепт для `recorder.save` (виды шагов: `launch_app`, `open_url`, `tap`, `swipe`, `type`, `key`, `sleep`), имя «Агент: <задача до 40 символов>», ключ `agent_<время>`, пропущенные и неудачные шаги не входят. `AgentError(Exception)` — понятные сообщения по-русски (выключено, секретная задача, секретный экран, защищённый экран, лимит дня, лимит шагов сеанса, не удалось разобрать ответ).
**API:** `POST /api/vlm/agent/step {serial, task, history}`, `POST /api/vlm/agent/do {serial, action}`, `POST /api/vlm/agent/recipe {task, history}`; `AgentError` → 400 со словами; номер шага и остаток (`step_no`, `left`) считаются по длине `history` и `config.AGENT_MAX_STEPS`.
**Квота:** каждый `step` — один запрос в дневной лимит (`usage.reserve` с пустым или уникальным ключом, не общим; вернуть квоту при сбое ответа/обрыве, как сделано в `plan.py` после исправлений ревью); ответ модели с `max_tokens` не меньше 600.
**Тесты:** разбор ответов (в рамках ```json), валидация каждого вида и отказ на `shell`, секрет в `type`, зацикливание, лимит шагов сеанса, выключенный помощник, секретный экран, возврат квоты, `do` исполняет только валидное, `recipe` проходит `normalize_steps`; мок всех внешних (скриншот, клиент, usage, safety).
- [ ] Тесты → реализация → полный прогон → коммит («ИИ-агент: пошаговый разбор, проверка действий, API»).

---

### Task 9: интерфейс ИИ-агента

**Files:** Create `frontend/js/tool-agent.js`, `frontend/css/agent.css`, `backend/tests/test_tool_agent_js.py`. Modify `frontend/index.html` (css, script после `tool-draft.js`), `frontend/strings/ru.json`; `frontend/js/tool-draft.js` — плитку «Черновик по описанию» убрать из реестра, а режим «Составить сразу, без выполнения» перенести кнопкой в агента (использует существующий `/api/vlm/plan`).
**Требования (спека C1, C4):** раскладка во всё окно: слева кадр телефона (`/api/devices/{serial}/frame?t=…`, обновляется после каждого шага; соотношение сторон экрана сохраняется), справа лента шагов (карточки «Агент предлагает» → «Выполнено / Пропущено / Остановлено / Ошибка»), внизу панель управления. Метка-прицел поверх кадра в точке `tap` с мягким пульсом (CSS-анимация, отключается при `prefers-reduced-motion`), стрелка для `swipe`, плашка с текстом для `type`. Кнопки: основной ярлык «Выполнить» (`Enter`), «Пропустить» (`S`), «Стоп» (`Esc` останавливает агента; закрытие окна при работающем агенте — через `armConfirm`), переключатель «Выполнять сам» с полем «шагов» (по умолчанию 15, максимум 30), для включения — второй клик-подтверждение. Индикатор «шаг N из M», расход дневного лимита (из `/api/vlm` данные `used_today`/`max_per_day`). Состояния: «Смотрю на экран…» (точки), «Жду вашего ответа», «Выполняю…», «Готово» (зелёная отметка), «Нужен человек» (янтарная плашка с причиной), «Остановлено»; ошибки словами с «Повторить шаг». «Сохранить как сценарий» (после завершения или остановки при ≥1 выполненном шаге) → `/api/vlm/agent/recipe` → `/api/recorder/save`, тост «Сохранено» с «Открыть в конструкторе». Выбор телефона — `pickPhone`-подобный список онлайн-телефонов (прочитать `devices.js`); примеры задач чипами. Конечный автомат в чистых функциях (`agentNext(state, event)`), тестируемых в Node: переходы (idle→thinking→proposed→doing→thinking→done), лимит шагов, остановка, режим «сам» делает шаг без ожидания, ошибка не теряет историю. Все тексты в `ru.json`. Проверить `node --check`.
- [ ] Тесты автомата → интерфейс → полный прогон → коммит («ИИ-агент: окно с кадром, лентой шагов и управлением»).

---

### Task 10: документация и сверка

**Files:** Modify `README.md`, `docs/guide.md`, `.claude/skills/farm-ux/SKILL.md`, `docs/public-api.md` (новые маршруты: `/api/phrases*`, `/api/vlm/agent/*`, `/api/gallery` поля; тест `test_public_api_doc.py` проверяет маршруты), `docs/superpowers/specs/2026-10-26-steps-phrases-agent-design.md` (подраздел «Отступления, найденные при реализации» — только если были).
**Требования:** руководство человеческим языком: как смотреть и править шаги добавленного сюжета; группы фраз и F1–F9; как пользоваться агентом, его пределы и безопасность; запись в «LaiXi parity checklist» (`Added 2026-10-26: …`); README — строка таблицы. Прочитать код, чтобы не выдумывать.
- [ ] Правки → полный прогон → коммит («Документация: шаги сюжетов, группы фраз, ИИ-агент»).
