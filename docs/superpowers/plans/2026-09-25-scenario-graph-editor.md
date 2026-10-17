# Граф вместо списка: редактируемая схема развилок Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** «Схема» в конструкторе сценариев (`static/js/recorder.js`) становится интерактивным холстом: каждый шаг — перетаскиваемая карточка, развилка веером расходится на цветные дорожки веток, вместо нынешнего read-only хребта.

**Architecture:** Данные не меняются (тот же `steps[]`, тот же `POST /api/recorder/save`) — только их отображение. Единственная правка бэкенда — необязательное поле `pos: [x, y]` у шага (`farm/recorder/steps.py`), хранящее позицию карточки в пикселях канвы. Развилка остаётся одним шагом с `arms[]`; каждая ветка рисуется как отдельная карточка, но позиция ветки не хранится — считается автоматически как дорожка справа от развилки (см. «Открытые вопросы спеки»: это решение снимает вопрос про `pos` у веток).

**Tech Stack:** Ванильный JS (без сборки, без фреймворка — как весь `static/js/`), позиционирование через CSS `position:absolute` + инлайн `left/top`, линии соединений — SVG, перетаскивание — Pointer Events API. Бэкенд — FastAPI/Python, без новых зависимостей.

## Global Constraints

- Копия в UI — существующими терминами проекта: «шаг», «развилка», «ветка», «блок», «экран». Не изобретать «нода», «edge» (см. `docs/superpowers/specs/2026-09-12-branching-scenarios-design.md`).
- Лимит ветвей одной развилки — 5 (`ARMS_MAX` в `steps.py`, `REC_ARMS_MAX` в `recorder.js`) — не меняется.
- Бэкенд не трогает `farm/recorder/codegen.py`, `farm/recorder/save.py`, `farm/api/recorder.py` — только `farm/recorder/steps.py`.
- Топология графа остаётся структурированной: свободна только раскладка (x, y карточки хребта), не связи. Развилка не превращается в «холст, где можно соединить что угодно с чем угодно» (см. `docs/superpowers/specs/2026-09-25-scenario-graph-editor-design.md`, раздел «Структурированный, не произвольный граф»).
- Каждый Python-шаг заканчивается прогоном полного набора тестов: `.venv/bin/pytest -q` из корня проекта.

---

## Файлы

| Файл | Что меняется |
|---|---|
| `farm/recorder/steps.py` | +поле `pos` в `normalize_step` |
| `tests/test_recorder_steps.py` | +тесты `pos`, правка двух существующих на новый набор ключей |
| `tests/test_recorder_api.py` | +тест: `pos` переживает `save` → `recipe` |
| `static/js/recorder.js` | новые функции `gr*` (раскладка, рендер, рёбра, перетаскивание); удаляются `schArms`; `schSpine` заменяется на `grRender`; `recPayload`/`recAdopt` несут `pos` |
| `static/css/recorder.css` | раздел «Схема сценария» переписывается под холст; правится комментарий, объяснявший прежний отказ от холста |

---

### Task 1: Бэкенд — поле `pos` у шага

**Files:**
- Modify: `farm/recorder/steps.py`
- Test: `tests/test_recorder_steps.py`
- Test: `tests/test_recorder_api.py`

**Interfaces:**
- Produces: `steps.normalize_step(raw)` возвращает словарь с ключом `"pos"` — `list[int, int] | None`. Остальные ключи (`kind, args, selector, param, note, texts, crop, point, any, arms, report`) не меняются.

- [ ] **Step 1: Написать падающие тесты в `tests/test_recorder_steps.py`**

Открыть файл, найти тест `test_нормализация_тапа_приводит_координаты_к_float` (строки 7-21) и заменить на версию с новым ключом:

```python
def test_нормализация_тапа_приводит_координаты_к_float():
    result = steps.normalize_step({"kind": "tap", "args": {"x": "0.5", "y": 1}})
    assert result == {
        "kind": "tap",
        "args": {"x": 0.5, "y": 1.0},
        "selector": None,
        "param": None,
        "note": "",
        "texts": [],
        "crop": None,
        "point": None,
        "any": None,
        "arms": None,
        "report": None,
        "pos": None,
    }
```

Найти тест `test_лишние_ключи_отбрасываются` (строки 39-46) и заменить набор ключей:

```python
def test_лишние_ключи_отбрасываются():
    result = steps.normalize_step({
        "kind": "key", "args": {"name": "back", "мусор": 1},
        "id": 7, "shot": "data:image/jpeg;base64,AAA", "alts": [1, 2],
    })
    assert result["args"] == {"name": "back"}
    assert set(result) == {"kind", "args", "selector", "param", "note",
                           "texts", "crop", "point", "any", "arms", "report",
                           "pos"}
```

Добавить новые тесты в конец файла:

```python
def test_позиция_узла_принимается():
    result = steps.normalize_step(
        {"kind": "tap", "args": {"x": 0.1, "y": 0.2}, "pos": [120, 340]})
    assert result["pos"] == [120, 340]


def test_позиция_узла_округляется_до_пикселя():
    result = steps.normalize_step(
        {"kind": "unlock", "args": {}, "pos": [12.6, -3.4]})
    assert result["pos"] == [13, -3]


def test_некорректная_позиция_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "unlock", "args": {}, "pos": [1]})
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "unlock", "args": {}, "pos": ["x", 1]})


def test_позиция_с_бесконечностью_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step(
            {"kind": "unlock", "args": {}, "pos": [float("inf"), 0]})


def test_позиция_доступна_развилке():
    result = steps.normalize_step({
        "kind": "branch", "args": {"name": "x"},
        "arms": [{"name": "a", "any": ['text="1"']}],
        "pos": [5, 6],
    })
    assert result["pos"] == [5, 6]
```

- [ ] **Step 2: Убедиться, что новые тесты падают**

Run: `.venv/bin/pytest tests/test_recorder_steps.py -q`
Expected: FAIL — `KeyError` / `AssertionError` на `pos` (поля ещё нет в `normalize_step`), плюс падение двух отредактированных тестов на несовпадении множества ключей.

- [ ] **Step 3: Добавить тест роундтрипа в `tests/test_recorder_api.py`**

Добавить в конец файла (рядом с `test_рецепт_отдаёт_шаги_записанного_сценария`, после строки 168):

```python
def test_позиция_узла_сохраняется_и_возвращается_в_рецепте(scen_dir):
    api_recorder.save_scenario({
        "key": "flow_pos", "meta": META,
        "steps": [{"kind": "unlock", "args": {}, "pos": [40, 80]}],
    })
    рецепт = api_recorder.recipe("flow_pos")
    assert рецепт["steps"][0]["pos"] == [40, 80]
```

- [ ] **Step 4: Реализовать `pos` в `farm/recorder/steps.py`**

Добавить импорт `math` в начало файла (после `import re`, строка 9):

```python
import math
import re
```

Добавить функцию `_pos` рядом с `_point` (после блока `_point`, то есть после строки 97, перед `ANY_MAX = 3`):

```python
def _pos(raw):
    """Позиция карточки шага на холсте схемы — пиксели, любой знак.

    В отличие от point у click (доля экрана 0..1), это координата на
    холсте конструктора, а не на экране устройства — диапазон не
    ограничен: холст можно прокрутить в любую сторону.
    """
    if raw in (None, []):
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise StepError("pos — пара чисел [x, y]")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise StepError("pos: числа должны быть конечными")
    return [round(x), round(y)]
```

В `normalize_step` (строки 236-260) добавить ключ `pos` в возвращаемый словарь, последней строкой перед закрывающей скобкой:

```python
def normalize_step(raw) -> dict:
    """Проверенный шаг ровно с ключами kind, args, selector, param, note,
    texts, crop, point, any, arms, report, pos. texts/crop/point — запасные
    слои резолвера цели у click, arms и report — только у branch, pos —
    позиция карточки на холсте «Схемы», не участвует в генерации кода."""
    if not isinstance(raw, dict):
        raise StepError("шаг должен быть объектом")
    kind = raw.get("kind")
    if kind not in ARGS:
        raise StepError(f"неизвестный шаг: {kind!r}")
    return {
        "kind": kind,
        "args": _args(kind, raw.get("args")),
        "selector": _selector(kind, raw.get("selector")),
        "param": _param(kind, raw.get("param")),
        "note": _text(raw.get("note")),
        "texts": _texts(kind, raw.get("texts")),
        "crop": _crop(kind, raw.get("crop")),
        "point": _point(kind, raw.get("point")),
        "any": _anchor(kind, raw.get("any")),
        "arms": _arms(kind, raw.get("arms")),
        "report": bool(raw.get("report", True)) if kind == "branch" else None,
        "pos": _pos(raw.get("pos")),
    }
```

- [ ] **Step 5: Прогнать тесты и убедиться, что они проходят**

Run: `.venv/bin/pytest tests/test_recorder_steps.py tests/test_recorder_api.py tests/test_branch.py -q`
Expected: PASS, все зелёные (включая `test_branch.py` — `_arms()` не менялась, но стоит перепроверить, что общий набор проходит).

- [ ] **Step 6: Прогнать полный набор тестов**

Run: `.venv/bin/pytest -q`
Expected: PASS, без регрессий в остальных модулях.

- [ ] **Step 7: Commit**

```bash
git add farm/recorder/steps.py tests/test_recorder_steps.py tests/test_recorder_api.py
git commit -m "feat(recorder): добавить позицию карточки шага (pos) в схему данных"
```

---

### Task 2: Фронтенд — раскладка и статичный рендер холста

**Files:**
- Modify: `static/js/recorder.js:581-743` (раздел «схема»)
- Modify: `static/css/recorder.css:123-263` (раздел «Схема сценария»)

**Interfaces:**
- Consumes: `REC.steps` (массив шагов с опциональным `step.pos: [x,y]`), `S.scenarios` (список сценариев для карточек блоков — как использует нынешний `schArms`), `schIcon(step)`, `schLabel(step)`, `schOpenStep(id)`, `schOpenBlock(key)` — эти четыре функции **не меняются**, используются как есть.
- Produces: `grRender()` — строка HTML холста; `recSchemeSpine()` (существующая функция, строка 711-714) зовёт её вместо `schSpine()`.

Все шаги ниже правят **`static/js/recorder.js`**, если не указано иное.

- [ ] **Step 1: Добавить константы холста**

Вставить перед `function schIcon(step) {` (строка 585) — после заголовка секции `/* --------------------------------------------------------------- схема */` (строка 581):

```javascript
/* Геометрия холста. Фиксированные пиксельные шаги, не проценты: карточки
   не тянутся под контент — длинная подпись обрезается многоточием (см.
   CSS), иначе рёбра, посчитанные по этим константам, разъехались бы с
   реальной высотой карточки. */
const GR_NODE_W = 190;     // ширина любой карточки
const GR_NODE_H = 44;      // высота карточки хребта (шаг, экшен, якорь, развилка)
const GR_ARM_H = 54;       // высота карточки ветки (имя + блок/«ничего не делать»)
const GR_COL_X = 16;       // x хребта
const GR_ROW_H = 70;       // шаг между карточками хребта по вертикали
const GR_ARM_X = 250;      // сдвиг дорожек веток вправо от развилки
const GR_ARM_ROW_H = 66;   // шаг между дорожками одной развилки
/* Цвет дорожки по индексу ветки — столько же оттенков, сколько ARMS_MAX
   в steps.py: развилка на 5 ветвей — предел и в бэкенде, и здесь. */
const GR_LANES = ['#6dc4ff', '#ffcf5c', '#ff9f6b', '#8fe3a0', '#d99bff'];
```

- [ ] **Step 2: Добавить `grLayout()` — расчёт позиций**

Вставить сразу после блока констант из Step 1:

```javascript
/* Раскладка холста: позиция каждой карточки хребта плюс дорожек развилки.
   Карточка без сохранённой step.pos встаёт в поток — следующей вниз по
   хребту от той точки, на которой остановилась предыдущая (в том числе
   перетащенная руками). Так ручная правка одной карточки не спорит с
   автоматической раскладкой всех, что идут после неё. */
function grLayout() {
    const pos = new Map();     // stepId -> {x, y}, карточки хребта
    const arms = new Map();    // stepId -> [{x, y}, ...], параллельно step.arms
    let y = 16;
    let maxX = GR_COL_X + GR_NODE_W;

    REC.steps.forEach(step => {
        const here = step.pos ? {x: step.pos[0], y: step.pos[1]} : {x: GR_COL_X, y};
        pos.set(step.id, here);

        let blockHeight = GR_ROW_H;
        if (step.kind === 'branch') {
            const armList = (step.arms || []).map((arm, i) => ({
                x: here.x + GR_ARM_X,
                y: here.y + i * GR_ARM_ROW_H,
            }));
            arms.set(step.id, armList);
            const armSpan = armList.length
                ? (armList.length - 1) * GR_ARM_ROW_H + GR_ARM_H
                : 0;
            blockHeight = Math.max(GR_ROW_H, armSpan + GR_ROW_H - GR_NODE_H);
            maxX = Math.max(maxX, here.x + GR_ARM_X + GR_NODE_W);
        }
        y = here.y + blockHeight;
        maxX = Math.max(maxX, here.x + GR_NODE_W);
    });

    return {pos, arms, width: maxX + 40, height: y + 40};
}
```

- [ ] **Step 3: Добавить рендер карточки хребта и карточки ветки**

Вставить после `grLayout()`:

```javascript
/* Карточка шага хребта. Ручка ⠿ — отдельный элемент: тащим за неё
   (Task 3), а клик по телу карточки открывает шаг в списке — то же
   разделение, что у строк списка (recRow), и по той же причине: внутри
   раскрытой карточки будут поля ввода, и перетаскивание за произвольное
   место отнимало бы у них выделение текста. */
function grNode(step, xy) {
    const [cls, icon] = schIcon(step);
    return `<div class="gr-node ${cls}" style="left:${xy.x}px;top:${xy.y}px;width:${GR_NODE_W}px" data-id="${step.id}">
      <span class="gr-grip" title="Перетащите карточку" onpointerdown="grDragStart(event, ${step.id})">⠿</span>
      <button class="gr-body" onclick="schOpenStep(${step.id})" title="Открыть шаг в списке">
        <i>${icon}</i><span class="gr-label">${esc(schLabel(step))}</span>
      </button>
    </div>`;
}

/* Карточка ветки развилки. Повторяет логику schArms (блок / «ничего не
   делать» / «блок не найден»), но как отдельная позиционированная карточка
   своей дорожки, а не строка внутри общего блока. Позиция не хранится —
   считается в grLayout() относительно родительской развилки. */
function grArmNode(arm, index, xy) {
    const цвет = GR_LANES[index % GR_LANES.length];
    const блок = (S.scenarios || []).find(s => s.key === arm.run);
    let inner, extra = '';
    if (!arm.run) {
        inner = '<span class="gr-arm-empty">ничего не делать</span>';
        extra = 'ghost';
    } else if (!блок) {
        inner = `<span class="gr-arm-lost">блок «${esc(arm.run)}» не найден</span>`;
        extra = 'missing';
    } else {
        inner = `<button class="gr-arm-block" onclick="schOpenBlock('${esc(arm.run)}')"
                   title="Открыть блок в конструкторе">↪ ${esc(блок.name)}</button>`;
    }
    return `<div class="gr-node gr-arm ${extra}"
         style="left:${xy.x}px;top:${xy.y}px;width:${GR_NODE_W}px;border-left-color:${цвет}">
      <div class="gr-arm-name" style="color:${цвет}">${esc(arm.name)}</div>
      ${inner}
    </div>`;
}
```

- [ ] **Step 4: Добавить рёбра (SVG) и сборку холста**

Вставить после `grArmNode()`:

```javascript
/* Кривая между двумя точками: пологая при горизонтальной связи (развилка
   → ветка), почти прямая при вертикальной (шаг → следующий шаг). Один и
   тот же кубический безье справляется с обоими — не нужно две формулы. */
function grEdgePath(x1, y1, x2, y2, color) {
    const midX = (x1 + x2) / 2;
    return `<path d="M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}"
      fill="none" stroke="${color}" stroke-width="2"/>`;
}

/* Рёбра холста: хребет — нейтральным цветом, дорожки развилки — цветом
   своей дорожки от развилки до карточки ветки и от карточки ветки до
   следующего шага хребта. Место слияния веток нигде не хранится отдельной
   сущностью: это просто следующий шаг в REC.steps, и все ветки рисуют
   ребро туда же — так же, как codegen.py безусловно эмитит его после
   развилки для любой сработавшей ветки. */
function grEdges(layout) {
    const parts = [];
    for (let i = 0; i < REC.steps.length; i++) {
        const step = REC.steps[i];
        const xy = layout.pos.get(step.id);
        const next = REC.steps[i + 1];

        if (step.kind === 'branch') {
            const armXY = layout.arms.get(step.id) || [];
            armXY.forEach((axy, ai) => {
                const цвет = GR_LANES[ai % GR_LANES.length];
                parts.push(grEdgePath(
                    xy.x + GR_NODE_W, xy.y + GR_NODE_H / 2,
                    axy.x, axy.y + GR_ARM_H / 2, цвет));
                if (next) {
                    const nxy = layout.pos.get(next.id);
                    parts.push(grEdgePath(
                        axy.x + GR_NODE_W, axy.y + GR_ARM_H / 2,
                        nxy.x + GR_NODE_W / 2, nxy.y, цвет));
                }
            });
        } else if (next) {
            const nxy = layout.pos.get(next.id);
            parts.push(grEdgePath(
                xy.x + GR_NODE_W / 2, xy.y + GR_NODE_H,
                nxy.x + GR_NODE_W / 2, nxy.y, '#3a4256'));
        }
    }
    return parts.join('');
}

/* Холст целиком: SVG с рёбрами под карточками (pointer-events:none — клики
   и перетаскивание обязаны доходить до карточек, не до линий), сверху —
   карточки хребта и веток. Ширина/высота — инлайн из раскладки: контейнер
   с абсолютно позиционированными детьми сам себя не размеряет, а скролл
   внешней панели (#recScheme.scroll) должен знать, докуда прокручивать. */
function grRender() {
    if (!REC.steps.length) {
        return '<div class="sch-empty">Шагов пока нет.<br>'
            + 'Нажмите «● Запись» и кликайте по экрану слева<br>'
            + 'или добавьте готовый шаг из группы «Добавить в сюжет».</div>';
    }
    const layout = grLayout();
    const edges = grEdges(layout);
    const nodes = REC.steps.map(step => {
        const xy = layout.pos.get(step.id);
        let html = grNode(step, xy);
        if (step.kind === 'branch') {
            const armXY = layout.arms.get(step.id) || [];
            html += (step.arms || [])
                .map((arm, i) => grArmNode(arm, i, armXY[i]))
                .join('');
        }
        return html;
    }).join('');
    return `<div class="gr-canvas" style="width:${layout.width}px;height:${layout.height}px">
      <svg class="gr-edges" width="${layout.width}" height="${layout.height}">${edges}</svg>
      ${nodes}
    </div>`;
}
```

- [ ] **Step 5: Удалить `schArms`, заменить `schSpine` на вызов `grRender`**

Удалить целиком функцию `schArms` (строки 592-616, включая комментарий над ней) — её работу теперь делает `grArmNode`.

Удалить целиком функцию `schSpine` (строки 626-642, включая комментарий над ней, начинающийся с `function schSpine() {`, до закрывающей `}` перед `function schOpenStep`).

В `recSchemeSpine()` (строка 711-714) заменить вызов:

```javascript
function recSchemeSpine() {
    const box = document.querySelector('#recScheme .sch-spine');
    if (box) box.innerHTML = grRender();
}
```

(тело меняется с `schSpine()` на `grRender()`, сигнатура и остальной код функции — без изменений).

- [ ] **Step 6: Переписать CSS-раздел «Схема сценария»**

В `static/css/recorder.css` заменить блок со 123 по 146 строку (комментарий «Схема сценария...» и правила `.sch`, `.sch-spine`, `.sch-node`, `.sch-node i`, `.sch-node.anchor i`, `.sch-node.block i`, `.sch-link`, `.sch-side h4`, `.sch-side + .sch-side`, `.sch-rule, .sch-gap`, `.sch-rule i`, `.sch-gap i`, `.sch-hits`, `.sch-empty`) на:

```css
/* Схема сценария: хребет сверху, отводы под ним.

   Хребет — интерактивный холст, а не свободный граф: карточку можно
   перетащить (Task 3), но нельзя соединить с произвольной другой — связи
   определяет порядок в REC.steps и arms развилки, холст только даёт им
   раскладку. Тот же вопрос про отводы (guards), что был здесь раньше,
   остаётся в силе и не пересмотрен: страж срабатывает где угодно на
   прогоне, а не в конкретной точке хребта, и рисовать его врезанным в
   карточку было бы враньём — отводы остаются отдельным блоком под
   холстом. Развилка — другое дело: она стоит в конкретной точке
   последовательности, и её веер веток на холсте — честное отображение
   того, что происходит (подробности —
   docs/superpowers/specs/2026-09-25-scenario-graph-editor-design.md).
   Панель живёт рядом с экраном устройства, а не в полноширинной модалке. */
.sch { display: flex; flex-direction: column; gap: var(--s4); padding: var(--s3); flex: 1; min-height: 0; }
.sch-side h4 { font-size: 11px; color: var(--dim); font-weight: 500; margin: 0 0 var(--s2); }
.sch-side + .sch-side { margin-top: var(--s4); }
.sch-rule, .sch-gap {
    display: flex; align-items: center; gap: var(--s2);
    font-size: 12px; padding: 3px 0;
}
.sch-rule i { color: var(--warn); font-style: normal; }
.sch-gap i { color: var(--bad); font-style: normal; }
.sch-hits { color: var(--dim); font-size: 11px; }
.sch-empty { color: var(--dim); font-size: 12px; }

/* ------------------------------------------------------- холст: карточки */

.gr-canvas { position: relative; }
.gr-edges { position: absolute; left: 0; top: 0; pointer-events: none; }

.gr-node {
    position: absolute;
    display: flex;
    align-items: center;
    gap: 6px;
    height: 44px;
    padding: 0 10px 0 6px;
    background: var(--panel2);
    border: 1px solid var(--line);
    border-radius: var(--r1);
    box-shadow: var(--e1);
    font-size: 12px;
}

.gr-node.dragging { opacity: .7; cursor: grabbing; z-index: 5; }

.gr-grip {
    color: var(--dim);
    cursor: grab;
    opacity: 0;
    user-select: none;
    font-size: 12px;
    flex: 0 0 auto;
    touch-action: none;
}
.gr-node:hover .gr-grip { opacity: .6; }

.gr-body {
    background: none;
    border: 0;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    flex: 1;
}
.gr-body:hover .gr-label { color: var(--accent-hi); }
.gr-body i { color: var(--accent); font-style: normal; flex: 0 0 12px; text-align: center; }

.gr-node.anchor .gr-body i { color: var(--accent-hi); }
.gr-node.block .gr-body i { color: var(--text2); }
.gr-node.branch .gr-body i { color: var(--busy); }

.gr-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
}

/* Карточка ветки — своя лента слева цветом дорожки (инлайн, из GR_LANES),
   плюс собственная высота: две строки (имя ветки и блок/«ничего не
   делать»), а не одна, как у карточки хребта. */
.gr-arm {
    height: 54px;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    gap: 2px;
    border-left-width: 3px;
    padding: 4px 10px;
}
.gr-arm-name { font-size: 11px; font-weight: 600; }
.gr-arm-empty { color: var(--dim); font-size: 11px; }
.gr-arm-block {
    background: none;
    border: 1px solid var(--accent-line);
    color: var(--accent);
    font: 11px var(--mono, ui-monospace, monospace);
    padding: 1px 7px;
    border-radius: 99px;
    cursor: pointer;
}
.gr-arm-block:hover { background: var(--accent-dim); }
.gr-arm-lost { color: var(--bad); font-size: 11px; overflow-wrap: anywhere; white-space: normal; }

.gr-arm.ghost { opacity: .6; }
/* Пропавший блок — отдельный сигнал (тонкая красная обводка), не
   перекрашивает всю карточку: цвет карточки — это цвет её дорожки. */
.gr-arm.missing { box-shadow: var(--e1), inset 0 0 0 1px var(--bad); }
```

Удалить старую секцию «схема: ветви развилки» (строки 184-263 исходного файла: `.sch-node` кнопка, `.sch-arms`, `.sch-arm`, `.sch-arm-name`, `.sch-arrow`, `.sch-block`, `.sch-none`, `.sch-lost`, `.sch-label`) — все её задачи закрыты новыми `.gr-*` правилами выше.

- [ ] **Step 7: Ручная проверка в браузере**

Требуется запущенный сервер (`./run.sh`), устройство подключать не обязательно — рендер холста проверяется по `REC.steps` напрямую через консоль браузера, без записи с телефона.

1. Открыть `http://127.0.0.1:8777`, открыть devtools → Console.
2. Вставить и выполнить (пример из README — вход → якорь → развилка на 3 ветки):

```javascript
REC.steps = [
  {id: 1, kind: 'launch_app', args: {package: 'com.android.chrome'}},
  {id: 2, kind: 'expect', args: {name: 'поиск'}, any: ['text="Поиск"']},
  {id: 3, kind: 'branch', args: {name: 'после входа'}, arms: [
    {name: 'онбординг', any: ['text="Пропустить"'], run: ''},
    {name: 'каталог', any: ['text="Каталог"'], run: ''},
    {name: 'пейволл', any: ['text="Подписка"'], run: 'udalennyy_blok'},
  ], report: true},
  {id: 4, kind: 'tap', args: {x: 0.5, y: 0.9}},
];
REC.nextId = 5;
document.querySelector('#recScheme .sch-spine').innerHTML = grRender();
```

3. Ожидается: четыре карточки хребта сверху вниз (запуск → якорь → развилка → тап), у развилки — три карточки веток справа, каждая своим цветом дорожки; ветка «пейволл» — с красной обводкой и текстом «блок «udalennyy_blok» не найден» (блока с таким ключом нет в `S.scenarios`).
4. Изменить позицию вручную и перерисовать без сброса раскладки: `REC.steps[0].pos = [16, 200]; document.querySelector('#recScheme .sch-spine').innerHTML = grRender();` — убедиться, что первая карточка встала на (16,200), а карточки после неё продолжили поток от этой точки вниз, не наехав друг на друга.
5. Проверить пустое состояние: `REC.steps = []; document.querySelector('#recScheme .sch-spine').innerHTML = grRender();` — должно показать текст-заглушку «Шагов пока нет...».

- [ ] **Step 8: Commit**

```bash
git add static/js/recorder.js static/css/recorder.css
git commit -m "feat(recorder): рисовать схему сценария как холст с карточками вместо хребта-списка"
```

---

### Task 3: Фронтенд — перетаскивание карточек и сохранение позиции

**Files:**
- Modify: `static/js/recorder.js`

**Interfaces:**
- Consumes: `grLayout`, `grRender`, `recFind(id)`, `recSave()`, `recSchemeSpine()` — все существующие/из Task 2.
- Produces: `grDragStart(ev, id)` — обработчик `onpointerdown` на ручке `.gr-grip` (уже подключён в `grNode()` из Task 2).

- [ ] **Step 1: Реализовать перетаскивание**

Вставить в `static/js/recorder.js` после функции `grRender()` (конец блока, добавленного в Task 2, перед `function recSetView`):

```javascript
/* Перетаскивание карточки хребта. Не HTML5 DnD (тот снап-based — годится
   для смены порядка в списке, но не для произвольных x,y) и не глобальные
   слушатели на document — Pointer Events с setPointerCapture: элемент сам
   получает все move/up, даже если курсор уйдёт с карточки во время тяги.

   Рёбра во время перетаскивания не перерисовываются — только на отпускании
   (recSchemeSpine() пересчитывает всю раскладку заново). Линии остаются
   на месте, пока карточка движется, и запрыгивают на отпускании: дешевле,
   чем пересчитывать SVG на каждый pointermove, и для перестановки карточек
   раз в несколько минут работы заметной разницы нет. */
function grDragStart(ev, id) {
    ev.preventDefault();
    const host = ev.target.closest('.gr-node');
    if (!host) return;
    const startX = ev.clientX, startY = ev.clientY;
    const baseLeft = host.offsetLeft, baseTop = host.offsetTop;

    host.setPointerCapture(ev.pointerId);
    host.classList.add('dragging');

    function onMove(e) {
        host.style.left = (baseLeft + e.clientX - startX) + 'px';
        host.style.top = (baseTop + e.clientY - startY) + 'px';
    }
    function onUp(e) {
        host.removeEventListener('pointermove', onMove);
        host.removeEventListener('pointerup', onUp);
        host.classList.remove('dragging');
        const step = recFind(id);
        if (step) {
            step.pos = [Math.round(baseLeft + e.clientX - startX),
                        Math.round(baseTop + e.clientY - startY)];
            recSave();
        }
        recSchemeSpine();
    }
    host.addEventListener('pointermove', onMove);
    host.addEventListener('pointerup', onUp);
}
```

- [ ] **Step 2: Пронести `pos` через сохранение (`recPayload`)**

В `recPayload()` (строки 1580-1618) внутри `REC.steps.map((step, index) => { ... })`, в объекте `out` — после блока `if (step.kind === 'click') { ... }` (перед `return out;`) добавить:

```javascript
        if (step.pos) out.pos = step.pos;
```

Полный блок после правки (для ориентира, менять только добавленную строку):

```javascript
        if (step.kind === 'click') {
            if (step.texts && step.texts.length) out.texts = step.texts;
            if (step.point) out.point = step.point;
            if (step.crop && Object.keys(assets).length < REC_ASSETS_MAX) {
                out.crop = recAssetName(index);
                assets[out.crop] = step.crop;
            }
        }
        if (step.pos) out.pos = step.pos;
        return out;
```

- [ ] **Step 3: Пронести `pos` через загрузку правки (`recAdopt`)**

В `recAdopt()` (строки 1881-1911) добавить ключ `pos` в возвращаемый объект `out` — после строки `arms: шаг.arms || null,`:

```javascript
        arms: шаг.arms || null,
        pos: шаг.pos || null,
```

- [ ] **Step 4: Ручная проверка в браузере**

Сервер должен быть запущен, устройство не требуется до последнего пункта.

1. Открыть `http://127.0.0.1:8777`, devtools → Console, выполнить фикстуру из Task 2 Step 7 (`REC.steps = [...]`, `recSchemeSpine()` вместо ручной перерисовки: `REC.nextId = 5; recSchemeSpine();`).
2. Открыть вкладку «Схема» в конструкторе (если не открыта — переключатель «Схема»/«Список» над списком шагов).
3. Мышью взять любую карточку хребта за ручку ⠿ и перетащить в другое место холста — карточка должна двигаться плавно, курсор — `grabbing`.
4. Отпустить кнопку мыши — карточка должна остаться на новом месте, рёбра — перерисоваться до неё и от неё корректно (без разрывов).
5. В консоли выполнить `console.log(REC.steps.find(s => s.id === 1).pos)` — должен быть массив `[x, y]`, отличный от исходной раскладки.
6. Открыть устройство на ферме (нужен реальный adb-девайс или эмулятор), начать новую запись, сохранить сценарий с парой шагов, перетащить карточку на «Схеме», сохранить ещё раз. Открыть сценарий на правку (`✎` в списке сценариев) — убедиться, что карточка открылась на том же месте, куда её передвинули (позиция пережила `save` → `recipe` → `recAdopt`).

- [ ] **Step 5: Commit**

```bash
git add static/js/recorder.js
git commit -m "feat(recorder): перетаскивание карточек схемы с сохранением позиции"
```

---

## Self-Review

**Spec coverage:**
- «Отображение» (типы карточек, цвета дорожек, пропавший блок) — Task 2. ✅
- «Редактирование» (перетаскивание меняет только позицию; двойной клик/клик открывает шаг или блок; кнопка «+ ветка» не меняется) — перетаскивание в Task 3, открытие шага/блока переиспользует `schOpenStep`/`schOpenBlock` без изменений, «+ ветка» уже не тронута (её код в `recBranchAdd` не входит в область правки). ✅
- «Структурированный, не произвольный граф» — топология рёбер выводится из `REC.steps`/`arms`, а не хранится независимо; перетаскивание меняет только `pos`. ✅
- «Позиция узла» (+поле `pos`, авто-раскладка без него, старые recipe.json открываются как есть) — Task 1 (бэкенд, необязательное поле) + `grLayout()` в Task 2 (авто-раскладка для шагов без `pos`). ✅
- «Что не меняется» (`codegen.py`, `save.py`, `api/recorder.py`, лимит веток, режимы «Список»/«Код») — ни один план-файл их не трогает. ✅
- Открытый вопрос спеки «формат pos» — решён в плане: пиксели холста (см. «Architecture»). Открытый вопрос «авто-раскладка новых шагов при записи» — решён: новый шаг не получает `pos` при `recPush()`, значит встаёт в поток автоматически при следующем рендере «Схемы» — поведения `recPush` не меняем.

**Placeholder scan:** код во всех шагах — рабочий, без TODO/TBD; ручная проверка вместо тестов — там, где в проекте нет JS-тестов вообще (не только в этой фиче).

**Type consistency:** `grLayout()` возвращает `{pos: Map, arms: Map, width, height}` — используется одинаково в `grEdges(layout)` и в сборке карточек внутри `grRender()`. `grNode(step, xy)`, `grArmNode(arm, index, xy)`, `grEdgePath(x1,y1,x2,y2,color)` — сигнатуры совпадают везде, где вызываются. `step.pos` — везде `[x, y]` пиксели, нигде не путается с нормализованными координатами `step.point` (0..1, только у `click`).
