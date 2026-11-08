# ИИ-мастер сюжетов + редизайн «Аккаунтов» (дизайн)

Решения пользователя: протокол — OpenAI-совместимый; локальная модель — Ollama; на телефоне — только безопасные шаги (рискованные требуют подтверждения); версии — неизменяемый снимок шагов по хэшу.

## Цель
Мастер «Описание → Шаги и ревью → Проверка на телефоне → Улучшения» внутри `#view-scen`, на основе существующих механизмов: `vlm/*`, редактор сюжетов (`recorder.js`), запуск `POST /api/run`, опрос `/api/jobs/{id}`. Второго редактора/исполнителя не создаём. Плюс редизайн раздела «Аккаунты» (`accounts.js/css`) с сохранением всех возможностей.

Не-цели: коммиты/push, новые зависимости pip (psutil не ставим), правка чужих тестов. Анти-цели: фиктивный прогресс, «проанализировал скриншоты» без поддержки картинок, поздний ответ, затирающий новую версию.

## Контракт API (префикс `/api/ai`, JSON, ошибки `{detail: "текст по-русски"}`)
Базовые типы:
- Step = формат recorder (`{kind, args}`), валидируется `recorder.steps.normalize_steps`.
- version = `sha256(canonical_json(steps))[:12]`.
- Finding = `{id, steps:[int], severity:"high|med|low", title, why, basis:"analysis|result|assumption", fix:{op:"replace|insert|delete", index:int, step?:Step}|null}` — `index` 0-based; `steps` непустой, индексы в пределах.

Маршруты:
1. `POST /models {url,key?}` → `{models:[{id}], error?}` (GET {base}/models; ключ из сохранённых, если не передан; в ответе ключ не возвращается).
2. `POST /probe {url?,model?}` → `{reachable:bool, text_ok:bool, vision:"yes|no|unknown", detail:str, checked_at}`. Vision: реальная проба — кадр с известным цветным квадратом/цифрой, вопрос про него; `yes` только если ответ верный, `no` если сервер отверг изображение (HTTP 4xx про image) или ответ неверный дважды, иначе `unknown`. Результат пишется в vlm settings как `vision` (`yes|no|unknown`), сбрасывается при смене url/model.
3. `POST /draft {task, serial?, clarify_answers?:[str]}` → `{status:"questions", questions:[str]}` или `{status:"steps", steps:[Step], notes:[str], needs_screen:bool, version}`; без serial и без vision — генерация только из текста, `needs_screen:true`, координаты не придумываются (tap только по тексту/селектору; если иначе — вопрос).
4. `POST /review {scenario?:key, steps:[Step], request_id}` → `{request_id, version, findings:[Finding]}`; каждый finding валидируется на сервере, невалидные отбрасываются (счётчик `dropped`).
5. `POST /versions {scenario_key, steps, label?}` → `{version, created:bool}` (идемпотентно); `GET /versions/{key}` → `[{version,created_at,label,steps_count}]`; `GET /versions/{key}/{version}` → `{steps}`.
6. `POST /run {scenario_key, version, serial, confirm_risky?:bool}` → `{run_id, job_id}`; сервер сам снимает снимок (version обязателен и сверяется с хэшем шагов сохранённого сюжета — иначе 409 «сюжет изменён»), ищет рискованные шаги (оплата/удаление/отправка/пароль; эвристика по тексту и kind `type` в поле пароля) → 409 `{risky:[{index,reason}]}` без `confirm_risky`; запускает через `runner.submit` на ОДНОМ телефоне; запись в `data/ai_runs.json`: `{run_id, job_id, scenario_key, version, serial, started_at}`.
7. `GET /runs?scenario_key=` → `[{run_id,job_id,version,serial,started_at,status,step_index,step_total,is_current:bool}]` (`is_current` = version == хэш текущих сохранённых шагов); `GET /runs/{run_id}` → то же + `timeline`, `error`, `phone_state:"online|offline"`; `POST /runs/{run_id}/stop` → отмена job; статус берётся из реального job.
8. `POST /analyze {run_id, request_id}` → `{request_id, version, observations:[{text,basis:"confirmed|probable|unverified"}], suggestions:[Finding], vision_used:bool, note?:str}`; скриншоты используются только если `vision == "yes"`, иначе `vision_used:false` и note с объяснением; ответ отвергается/помечается, если `version` run ≠ текущая — на клиенте.
9. `GET /hardware` → `{os, arch, cpu:{name,cores}, ram_gb, disk_free_gb, gpus:[{name,vram_gb?}], exact:{...поле:bool}}` (ферма, не браузер; `exact` отличает измеренное от оценки).
10. Локальная модель (Ollama): `GET /local/status` → `{ollama:{installed,running,version?}, models:[{name,size_gb}], recommended:[{id,title,download_gb,ram_gb_est,vision:bool,why,fits:bool,estimate:true}], install_path}`; `POST /local/pull {model}` → `{task_id}` (требует `confirm:true` и возвращённых ранее `download_gb`/`install_path` на экране); `GET /local/tasks/{id}` → `{state:"queued|running|done|error|cancelled", stage, completed_bytes?, total_bytes?, percent|null, error?, can_cancel, can_retry}` (percent считается только из реальных bytes Ollama `/api/pull`, иначе null); `POST /local/tasks/{id}/cancel`; `POST /local/connect {model}` → записывает url=`http://127.0.0.1:11434/v1`, model, затем probe. Установка самого Ollama — не автоматическая: если не найден, `status` даёт официальную ссылку и шаг «Скачайте и запустите Ollama», после чего «Проверить снова».

Ограничение выдачи: ключ модели никогда не попадает в ответы, логи и JS (MASK как в vlm).

## Надёжность
Все ответы модели парсятся строго; неполный JSON → `502 {detail}`; идемпотентность по `request_id`; на клиенте монотонный счётчик запросов — устаревший ответ игнорируется; тайм-аут `cfg.timeout`; клиент не имеет отмены сокета, поэтому отмена = игнорирование результата.

## Фронтенд
Новые файлы `frontend/js/ai-wizard.js`, `frontend/css/ai-wizard.css`; подключение в `index.html` и вход на странице сюжетов (`#view-scen`). Шапка мастера: имя сюжета, версия-хэш, этап, «сохранено/черновик», «проверка относится к текущей версии / устарела». Черновик из генерации — только в памяти до явного «Сохранить» (`POST /api/recorder/save`, переиспользуя редактор). Правки ревью — построчный diff «было → стало», принять/отклонить каждую. Любое изменение шагов → `is_current` false → бейдж «нужна новая проверка», запуск по старой версии не подтверждает новую. «Сохранить копией» = save с новым ключом. Настройки ИИ: две карточки (сервер / локальная модель) с честными состояниями и прогрессом.

## Аккаунты
Сохранить: поиск, фильтры, платформы, чекбоксы/массовые, панель выбранных, импорт, показ пароля по клику, клавиатуру, черновики. Улучшить: иерархия карточек/строк, статус-бейджи только из `new/active/login/banned`, связь с телефоном, состояния загрузка/пусто/ошибка/нет результатов, тосты после действий, маскирование логина/прокси по умолчанию где уместно, адаптив <= 640px, видимый `:focus-visible`. Не добавлять 2FA/cookies/выдуманные метрики.

## Проверка
pytest для: привязка findings к шагам, применение одной правки, версия↔запуск, сброс is_current, stop/offline, probe возможностей, ошибки pull/конфига. В конце — браузерный проход (широкий/узкий). Реальная модель/телефон — только если доступны; иначе отметить как непроверенное.
