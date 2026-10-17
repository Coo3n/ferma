# Сервер (backend/)

Python-пакет `farm` на FastAPI. Запуск: `./run.sh` из корня или
`cd backend && ../.venv/bin/python -m farm.server`.

## Карта модулей

| Модуль | За что отвечает |
|---|---|
| `server.py` | собирает приложение: роутеры, защита, раздача сайта |
| `config.py` | все настройки и пути; каждую можно задать переменной `FARM_*` |
| `security.py` | защита API от чужих страниц (Host/Origin) и вход по токену |
| `api/` | HTTP-роутеры по разделам — ниже таблица |
| `devices/registry.py` | реестр телефонов: кто подключён, заряд, температура, имена, группы, теги |
| `devices/runner.py` | очередь запусков: поток на телефон, отмена, остановка на человеке (HELD) |
| `devices/pool.py` | кэш подключений uiautomator2 |
| `devices/network.py` | сторож телефонов по сети (adb over TCP) |
| `context.py` | `ctx` — всё, что может сценарий: клики, ввод, якоря, развилки, сторож |
| `scenarios.py` | поиск сценариев в `scenarios/`, загрузка, проверка готовности |
| `resolve.py` | поиск цели: селектор → текст → OCR → картинка → координаты |
| `guards.py` | стражи: `guards/*.json`, какие окна закрывать самим |
| `obstacle.py` | слепок незнакомого экрана — чем его узнать в следующий раз |
| `deviations.py` | журнал «Проблем»: одинаковые сливаются в одну строку |
| `schedule.py` | смены: запуск по дням и окнам времени |
| `accounts.py` | аккаунты соцсетей и раздача по телефонам |
| `recorder/` | конструктор: шаги ⇄ код сценария, сохранение, библиотека шагов |
| `control/` | действия над телефоном: ввод, приложения, скриншоты, стабильность экрана |
| `streaming/` | трансляция экрана (MJPEG): один захват на телефон, сколько угодно зрителей |
| `ui/` | разбор дерева экрана и подбор селекторов (без adb) |
| `vision/` | OCR и поиск по картинке (необязательные зависимости) |
| `adb.py` | обёртка над командой `adb` |

### API по разделам

| Файл | Пути |
|---|---|
| `api/devices.py` | `/api/devices` — список, имя, группа, теги, подготовка, починка |
| `api/screen.py` | `/api/devices/{serial}/stream·frame·thumb·action·screenshot·record` |
| `api/bulk.py` | `/api/bulk/*` — массовые действия с разбросом, установка APK, файлы |
| `api/scenarios.py` | `/api/scenarios`, `/api/run`, `/api/run/preflight` |
| `api/jobs.py` | `/api/jobs` — журнал, отмена, решение по остановке, артефакты |
| `api/recorder.py` | `/api/recorder/*` — конструктор |
| `api/detours.py` | `/api/detours` — отводы (выученные «как закрыть окно») |
| `api/deviations.py` | `/api/deviations` — проблемы |
| `api/schedule.py` | `/api/schedules` — смены |
| `api/accounts.py` | `/api/accounts` — аккаунты |
| `api/network.py` | `/api/network` — телефоны по сети |
| `api/system.py` | `/api/status`, `/api/adb/restart` |

## Как добавить фичу

### Пример 1. Новое действие с телефоном — «Сделать звук на ноль»

1. `backend/farm/api/screen.py` — функция и строка в `ACTIONS`:

   ```python
   def _mute(serial, p):
       adb.shell(serial, "media volume --stream 3 --set 0", timeout=SHELL_TIMEOUT)

   ACTIONS = {
       ...
       "mute": _mute,
   }
   ```

2. Готово на сервере: `POST /api/devices/{serial}/action {"type": "mute"}`.
   Массовое действие получает его бесплатно: `bulkAction({type: 'mute'}, 'Без звука')`.
3. Кнопка в пульте — см. [frontend.md](frontend.md#как-добавить-фичу).
4. Тест — `backend/tests/test_pult_api.py` показывает, как подменить `adb.shell`.

### Пример 2. Новый API — «сколько телефонов в каждой группе»

```python
# backend/farm/api/devices.py
@router.get("/groups/count")
def groups_count():
    counts = {}
    for d in registry.all():
        counts[d.group or "без группы"] = counts.get(d.group or "без группы", 0) + 1
    return counts
```

Роутер `devices.router` уже подключён в `api/__init__.py`. Новый файл роутера
нужно подключить там же строкой `router.include_router(<модуль>.router)`.

### Пример 3. Новый сценарий

```python
# backend/scenarios/open_settings.py
NAME = "Открыть настройки"
DESCRIPTION = "Открывает настройки и возвращается домой"
PARAMS = {"pause": {"label": "Пауза, с", "type": "number", "default": 2}}

def run(ctx):
    ctx.launch_app("com.android.settings")
    ctx.sleep(ctx.params["pause"])
    ctx.home()
```

Файл появится в «Сценариях» сам — сервер следит за папкой.

## Тесты

```bash
cd backend
../.venv/bin/python -m pytest -q              # все
../.venv/bin/python -m pytest -q tests/test_watch.py   # один файл
```

Телефон не нужен ни одному тесту: adb, экран и время подменяются
(`monkeypatch`). Тесты JS-логики сайта гоняются через `node`.
