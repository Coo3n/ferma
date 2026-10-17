# UX инспектора — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Развести наблюдение и управление по разным вкладкам и связать кнопку инспектора с местом, где появляется результат.

**Architecture:** Таб «Инспектор» разрезается надвое. Инспекция (выбранный элемент, UI-дерево, logcat) остаётся, управление (запуск пакета, ссылка, Force-stop, `adb shell`) уезжает в новый таб «Устройство». Общий приёмник вывода `#inspOut` расщепляется на два, потому что кнопка и её вывод иначе окажутся в разных вкладках. `toggleInspector()` после успешного снимка переключает колонку на таб «Инспектор».

**Tech Stack:** Ванильный JS без сборки, правки только в `static/`.

Спека: `docs/superpowers/specs/2026-07-25-inspector-ux-design.md`

## Global Constraints

- **Git в проекте не заведён — шагов Commit в этом плане нет.** Это осознанный выбор пользователя, а не упущение. Откат — только руками
- Серверный код не трогаем: `farm/inspect.py`, `farm/server.py` и 25 тестов остаются как есть
- Правки только в `static/index.html` и `static/inspector.js`
- CSS вкладок менять не нужно: `.tab{flex:1}` раскладывает любое их число
- Порядок табов: Сценарии, Задачи, Инспектор, Устройство
- Весь текст интерфейса — по-русски, в тон существующему
- `showTab('insp')` вызывается **после** успешного получения данных, не до

---

### Task 1: Разрезать таб на «Инспектор» и «Устройство»

**Files:**
- Modify: `static/index.html` — блок вкладок (~строка 358), панель `#pane-insp` (~393–434), функция `runShell` (~1010)

**Interfaces:**
- Consumes: существующие `showTab(name)`, `launchPkg()`, `stopPkg()`, `loadPackages()`, `openUrl()`, `runShell()`, `dumpUi()`, `showLogcat()`
- Produces: панель `#pane-dev`, приёмник вывода `#devOut`; `#inspOut` сужается до дерева и logcat

- [ ] **Step 1: Добавить четвёртую вкладку**

В `static/index.html` заменить блок вкладок:

```html
    <div class="tabs">
      <div class="tab on" data-pane="scen" onclick="showTab('scen')">Сценарии</div>
      <div class="tab" data-pane="jobs" onclick="showTab('jobs')">Задачи</div>
      <div class="tab" data-pane="insp" onclick="showTab('insp')">Инспектор</div>
    </div>
```

на:

```html
    <div class="tabs">
      <div class="tab on" data-pane="scen" onclick="showTab('scen')">Сценарии</div>
      <div class="tab" data-pane="jobs" onclick="showTab('jobs')">Задачи</div>
      <div class="tab" data-pane="insp" onclick="showTab('insp')">Инспектор</div>
      <div class="tab" data-pane="dev" onclick="showTab('dev')">Устройство</div>
    </div>
```

- [ ] **Step 2: Переписать панель инспектора и добавить панель устройства**

В `static/index.html` заменить целиком блок от `<!-- инспектор -->` до закрывающего `</div>` панели (сейчас это строки 392–434, заканчивается на `<pre class="log" id="inspOut"></pre>` и следующей за ним `</div>`):

```html
    <!-- инспектор: только чтение UI -->
    <div class="pane" id="pane-insp">
      <div class="box">
        <h3>Выбранный элемент</h3>
        <div class="row">
          <label class="kb">
            <input type="checkbox" id="inspAll" style="accent-color:var(--accent)"
                   onchange="inspToggleAll(this.checked)"> все узлы
          </label>
        </div>
        <div class="selbox" id="inspSel"></div>
      </div>
      <div class="box">
        <h3>Дамп экрана</h3>
        <div class="row">
          <button class="sm" onclick="dumpUi()">UI-дерево</button>
          <button class="sm" onclick="showLogcat()">logcat</button>
          <button class="sm" onclick="document.getElementById('inspOut').textContent=''">очистить</button>
        </div>
      </div>
      <pre class="log" id="inspOut"></pre>
    </div>

    <!-- устройство: управление -->
    <div class="pane" id="pane-dev">
      <div class="box">
        <h3>Запуск приложения</h3>
        <div class="row">
          <input type="text" id="pkgInput" placeholder="com.android.settings" list="pkgList">
          <datalist id="pkgList"></datalist>
          <button onclick="launchPkg()">Открыть</button>
        </div>
        <div class="row">
          <button class="sm" onclick="loadPackages()">Загрузить список приложений</button>
          <button class="sm" onclick="stopPkg()">Force-stop</button>
        </div>
        <div class="row">
          <input type="text" id="urlInput" placeholder="https://example.com">
          <button onclick="openUrl()">Ссылка</button>
        </div>
      </div>
      <div class="box">
        <h3>adb shell</h3>
        <div class="row">
          <input type="text" id="shellInput" placeholder="dumpsys battery"
                 onkeydown="if(event.key==='Enter')runShell()">
          <button onclick="runShell()">↵</button>
        </div>
        <div class="row">
          <button class="sm" onclick="document.getElementById('devOut').textContent=''">очистить</button>
        </div>
      </div>
      <pre class="log" id="devOut"></pre>
    </div>
```

- [ ] **Step 3: Направить вывод shell в свой приёмник**

В `static/index.html` заменить функцию `runShell`:

```js
async function runShell(){
  const cmd = $('shellInput').value.trim();
  if(!cmd) return;
  try{
    const r = await act({type: 'shell', cmd});
    $('inspOut').textContent = r.output || '(пусто)';
  }catch(e){ $('inspOut').textContent = e.message; }
}
```

на:

```js
async function runShell(){
  const cmd = $('shellInput').value.trim();
  if(!cmd) return;
  // Свой приёмник, а не общий с деревом и logcat: кнопка живёт во вкладке
  // «Устройство», и её вывод должен остаться там же.
  try{
    const r = await act({type: 'shell', cmd});
    $('devOut').textContent = r.output || '(пусто)';
  }catch(e){ $('devOut').textContent = e.message; }
}
```

- [ ] **Step 4: Проверить в браузере**

Перезапустить ферму и открыть `http://127.0.0.1:8777`.

Expected:
- четыре вкладки в правой колонке, ширина ровная;
- «Инспектор» содержит только выбранный элемент, кнопки дампа и вывод;
- «Устройство» содержит запуск приложения, ссылку и `adb shell`;
- `dumpsys battery` в «Устройстве» пишет результат под собой;
- «UI-дерево» и «logcat» в «Инспекторе» пишут в свой вывод и результат `dumpsys` не затирают;
- «Загрузить список приложений» наполняет подсказки поля пакета в том же табе;
- «очистить» в каждом табе чистит только свой вывод;
- в консоли браузера ошибок нет.

---

### Task 2: Связать кнопку инспектора с вкладкой

**Files:**
- Modify: `static/inspector.js` — функции `inspectorLoad` и `inspPanel`

**Interfaces:**
- Consumes: `showTab(name)` из `index.html`, `#pane-insp` и `#inspSel` из Task 1
- Produces: поведение автопереключения; кнопка включения в пустом состоянии панели

- [ ] **Step 1: Переключать вкладку после успешного снимка**

В `static/inspector.js` в функции `inspectorLoad` заменить:

```js
    $('btnInspReload').style.display = '';
    $('inspLayer').style.display = 'block';
    startStream();          // подставит INSP.data.screenshot
```

на:

```js
    $('btnInspReload').style.display = '';
    $('inspLayer').style.display = 'block';
    // Переключаем вкладку только после удачного снимка. Сделай это раньше —
    // при отвалившемся устройстве пользователя выбросит на пустой таб без
    // объяснения причины.
    showTab('insp');
    startStream();          // подставит INSP.data.screenshot
```

- [ ] **Step 2: Сделать пустое состояние панели действием**

В `static/inspector.js` в функции `inspPanel` заменить:

```js
  if(!INSP.on){
    box.innerHTML = '<div class="empty">Включите инспектор и ткните в элемент.</div>';
    return;
  }
```

на:

```js
  if(!INSP.on){
    box.innerHTML = '<div class="empty">Инспектор выключен.<br><br>'
      + '<button class="sm" onclick="toggleInspector()">🔍 включить инспектор</button></div>';
    return;
  }
```

- [ ] **Step 3: Отрисовать пустое состояние при загрузке страницы**

`inspPanel()` сейчас зовётся только из `inspectorLoad`, `inspectorOff` и
обработчика клика. На свежей загрузке страницы `#inspSel` остаётся пустым
`<div>`, и кнопка из Step 2 не появится, пока инспектор хоть раз не включат —
то есть ровно в тот момент, когда она нужнее всего.

В `static/inspector.js` в конце IIFE, после строки
`window.addEventListener('resize', inspSyncRect);`, добавить вызов:

```js
  window.addEventListener('resize', inspSyncRect);

  // Иначе вкладка «Инспектор» на свежей странице показывает пустой блок
  // вместо кнопки включения.
  inspPanel();
})();
```

Функция `inspPanel` объявлена ниже по файлу, но объявления функций
поднимаются, поэтому вызов из IIFE выше по тексту работает.

- [ ] **Step 4: Проверить в браузере**

Перезагрузить `http://127.0.0.1:8777`.

Expected:
- сразу после загрузки открыть вкладку «Инспектор» — видна кнопка «🔍 включить
  инспектор», а не пустой блок;
- открыть вкладку «Сценарии», нажать «🔍 инспектор» над экраном — правая колонка сама встаёт на «Инспектор», панель показывает подсказку ткнуть в элемент;
- клик по элементу заполняет панель селектором;
- выключение инспектора **не** меняет активную вкладку;
- кнопка «🔍 включить инспектор» в пустом состоянии включает режим;
- отключить устройство от USB и нажать «🔍 инспектор» — всплывает ошибка, вкладка **не** переключается;
- в консоли браузера ошибок нет.

---

### Task 3: Обновить README

**Files:**
- Modify: `README.md` — раздел «Интерфейс», раздел «Визуальный инспектор»

**Interfaces:**
- Consumes: всё из Task 2
- Produces: ничего

- [ ] **Step 1: Описать четыре вкладки**

В `README.md` заменить абзац:

```markdown
**Справа — три вкладки.** «Сценарии» — список, форма параметров и запуск на всех
отмеченных устройствах. «Задачи» — журнал с живыми логами и артефактами.
«Инспектор» — выбранный элемент с готовым селектором, список приложений, запуск
по имени пакета, `adb shell`, дамп UI-дерева и logcat.
```

на:

```markdown
**Справа — четыре вкладки.** «Сценарии» — список, форма параметров и запуск на
всех отмеченных устройствах. «Задачи» — журнал с живыми логами и артефактами.
«Инспектор» — выбранный элемент с готовым селектором, дамп UI-дерева и logcat.
«Устройство» — запуск приложения по имени пакета, открытие ссылки, Force-stop
и `adb shell`.

Наблюдение и управление разведены намеренно: во вкладке «Инспектор» ничего не
меняет состояние телефона, а во вкладке «Устройство» — меняет всё.
```

- [ ] **Step 2: Дополнить раздел про инспектор**

В `README.md` в разделе «Визуальный инспектор» после абзаца, начинающегося
«Клик в режиме инспектора **не тапает устройство**», добавить:

```markdown
Нажатие «🔍 инспектор» само открывает вкладку «Инспектор» справа — там
появляется выбранный элемент. Выключение инспектора вкладку не меняет.
```

- [ ] **Step 3: Проверить README**

Run: `grep -n "четыре вкладки\|Устройство» — запуск\|сама открывает\|само открывает" README.md`
Expected: три совпадения, текст на месте.

---

## Отступления от спеки

1. **Блок кнопок дампа получил заголовок «Дамп экрана».** В спеке он был
   безымянным продолжением блока `adb shell`. После переезда `adb shell` в
   другую вкладку кнопки остались бы без шапки, в отличие от всех соседних
   блоков — заголовок добавлен ради единообразия.
2. **Шагов Commit нет.** Git в проекте не заведён по решению пользователя.
