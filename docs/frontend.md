# Сайт (frontend/)

Обычные статические файлы: открываются в браузере как есть, без сборки, без
npm и без интернета. Сервер раздаёт их сам; отдельно — `python3 frontend/dev_server.py`.

## Карта файлов

| Файл | За что отвечает |
|---|---|
| `index.html` | разметка всех разделов; раздел = `<section class="view" id="view-…">` |
| `icons.svg` | иконки (Lucide), вклеиваются в страницу при загрузке |
| `design/tokens.css` | дизайн-токены — см. [design-system.md](design-system.md) |
| `strings/ru.json` | все тексты интерфейса |
| `css/base.css` | кнопки, поля, чипы, модалка, тосты |
| `css/layout.css` · `fleet.css` · `screen.css` · `work.css` · … | стили разделов |
| `js/i18n.js` | `t('ключ')` и подстановка текстов в разметку |
| `js/core.js` | `S` (состояние), `api()`/`post()`, `toast()`, `armConfirm()`, `emptyBig()` |
| `js/app.js` | навигация `showView()`, опросы сервера, старт страницы |
| `js/fleet.js` | раздел «Ферма»: плитки, фильтры, выбор, перетаскивание файлов |
| `js/pult.js` | пульт телефона |
| `js/screen.js` | экран телефона: трансляция, жесты, клавиши |
| `js/bulk.js` | массовые действия, синхронное управление, загрузка файлов |
| `js/rundialog.js` | окно «Запуск сценария» — единственный вход для запусков |
| `js/jobs.js` · `deviations.js` · `schedule.js` · `accounts.js` | разделы «Запуски», «Проблемы», «Расписание», «Аккаунты» |
| `js/recorder.js` · `steptools.js` · `workspace.js` · `repair.js` | конструктор сценариев |
| `js/notify.js` | «Ферма ждёт вас»: заголовок вкладки, звук, уведомление |

Порядок подключения скриптов задан в конце `index.html`: `i18n.js` первым,
`app.js` последним.

## Как всё связано

```
app.js: опросы каждые 2–3 с
   │  GET /api/devices, /api/jobs, /api/status
   ▼
S.devices, S.jobs …  (core.js)
   │
   ▼
renderFleet(), pultRender(), pollJobs() …   ← перерисовывают только изменения
```

Кнопки в разметке вызывают функции напрямую: `onclick="pultShot()"`. Функции
разделов — глобальные; имя начинается с раздела (`pult…`, `fleet…`, `rec…`),
поэтому по имени сразу видно, где искать.

## Готовые помощники — используйте их

| Нужно | Функция |
|---|---|
| запрос к серверу | `api(path, options)`, `post(path, body)` |
| сообщение | `toast(t('раздел.ключ'), 'ok' \| 'bad')` |
| опасное действие (второй клик подтверждает) | `armConfirm(btn, 'текст')` |
| неактивная кнопка с причиной | `disableWithReason(btn, условие, 'почему')` |
| диалог | заполнить `mTitle` / `mBody` / `mActs`, вызвать `openModal()` |
| пустой экран | `emptyBig({art, title, text, action})` |
| запустить сценарий | `openRunDialog({scenario})` |
| действие на выбранных телефонах | `bulkAction({type: …}, 'Название')` |
| текст | `t('раздел.ключ', {n: 3})` |

## Как добавить фичу

### Пример: кнопка «Без звука» в пульте (сервер — пример 1 в backend.md)

1. Текст — в `strings/ru.json`:

   ```json
   "pult.bez_zvuka": "Без звука",
   ```

2. Кнопка — в `index.html`, в блок `.pult-keys`:

   ```html
   <button class="key" data-live onclick="act({type:'mute'})" data-t="pult.bez_zvuka">
       <svg class="ic" aria-hidden="true"><use href="#i-volume-low"/></svg>Без звука</button>
   ```

   `data-live` — кнопка неактивна, пока экраном нельзя управлять.

3. Проверка: `cd backend && ../.venv/bin/python -m pytest -q tests/test_strings.py` —
   тест сверит, что ключ есть в `ru.json`.

### Пример: сообщение из JS

```js
toast(t('pult.video_sohraneno'), 'ok');
setText(btn, t('pult.prodolzhit_zapis', {n: 3}));   // "Продолжить запись ({n})"
```
