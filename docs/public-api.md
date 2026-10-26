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
| `GET /api/gallery` | готовые сюжеты; у каждого `kind` (`recipe` или `code`), `editable`, `steps_text` (шаги словами: `text` и `depth`), `params` |
| `POST /api/gallery/{key}/add` | добавить готовый сюжет в «Мои» (рецепт — как записанный сценарий; занятое имя получает суффикс `_2`) |
| `GET /api/phrases` | группы быстрых фраз F1–F9 |
| `PUT /api/phrases` | заменить все группы целиком (до 30 групп, до 100 фраз в группе) |
| `POST /api/phrases/import` | добавить фразы из текста файла (`.txt`/`.csv`) в группу |
| `GET /api/phrases/export` | скачать группу (`?group=`) по фразе в строке |
| `POST /api/vlm/plan` | черновик по описанию: нейросеть предлагает список шагов, ничего не нажимая |
| `POST /api/vlm/agent/step` | ИИ-агент: следующее действие (`action`), «готово» (`done`) или «нужен человек» (`ask`); телефон не трогает |
| `POST /api/vlm/agent/do` | ИИ-агент: выполнить на телефоне одно проверенное действие, ответ `{"ok": true}` |
| `POST /api/vlm/agent/recipe` | ИИ-агент: собрать из истории шагов рецепт для `POST /api/recorder/save` |

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
`stop`, `close_recent`, `url`, `unlock`, `shell`, `screen_off`, `rotate`, `resolution_set`,
`resolution_reset`, `contacts_add`, `contacts_clear`. Поля каждого видно в
справке `/docs`.

Агент работает, только если включён помощник-нейросеть; запросы идут в общий
дневной лимит нейросети. Сессия агента на сервере не хранится: историю шагов
(`history`) присылает вызывающий, сервер каждый раз проверяет её заново и
выполняет только разрешённые действия (нажать, провести, ввести текст, клавиша,
открыть приложение или ссылку, подождать), без `shell`.

## Осторожно

- `shell` выполняет любую команду на телефоне. Не открывайте ферму в сеть без
  `FARM_TOKEN`.
- Пароли аккаунтов лежат в `GET /api/accounts/{id}/password`, ключ adb — в
  резервной копии. Берегите токен так же, как их.
