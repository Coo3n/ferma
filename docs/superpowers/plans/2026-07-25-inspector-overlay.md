# Визуальный инспектор UI — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кликнуть по элементу на картинке экрана и сразу получить готовый селектор для сценария, вместо чтения сырого XML-дампа.

**Architecture:** Новый модуль `farm/inspect.py` разбирает XML-дамп в плоский список узлов с предпосчитанными селекторами и числом совпадений. Эндпоинт `/api/devices/{serial}/inspect` отдаёт узлы вместе с base64-скриншотом одним атомарным ответом. Фронт (`static/inspector.js`) замораживает кадр, рисует рамки поверх и показывает панель выбранного элемента.

**Tech Stack:** Python 3 + FastAPI, `xml.etree.ElementTree` (стандартная библиотека), pytest, ванильный JS без сборки.

Спека: `docs/superpowers/specs/2026-07-25-inspector-overlay-design.md`

## Global Constraints

- Никаких новых рантайм-зависимостей. `xml.etree.ElementTree` — стандартная библиотека. В `requirements.txt` добавляется только `pytest` (для тестов)
- `farm/inspect.py` **не импортирует** `farm.adb`, `farm.control` и `farm.u2pool` — принимает XML-строку и размеры экрана. Это условие тестируемости без устройства
- Инвариант: `nodes[i].id == i`. Фронт адресует узлы индексом массива, сервер обязан его выдерживать
- `bounds` в ответе — доли `0..1`, зажатые в этот диапазон, в порядке `[x1, y1, x2, y2]`
- Все сообщения об ошибках и текст UI — по-русски, в тон существующему коду
- Комментарии в коде — по-русски, как в остальных модулях (`farm/control.py`, `farm/screen.py`)
- Ограничители автоподъёма: 4 уровня, 4× площади, 0.95 площади экрана. Вынесены в константы модуля
- Приоритет селекторов ровно такой: `resourceId` → `description` → `text` → комбинация с `className` → `instance` → `ctx.tap` по координатам

---

### Task 1: Каркас — git, pytest, разбор bounds

**⚠️ Внимание:** `/Users/hlamov.ilya/Desktop/android-farm` сейчас **не git-репозиторий**. Первый шаг его создаёт. Если это нежелательно — выкинуть шаги 1–2 и все шаги «Commit» из плана.

**Files:**
- Create: `farm/inspect.py`
- Create: `tests/test_inspect.py`
- Modify: `requirements.txt`
- Create: `.gitignore` (дополнить существующий)

**Interfaces:**
- Consumes: ничего
- Produces: `InspectError`, `Node` (dataclass), `parse_bounds(raw: str | None, width: int, height: int) -> tuple[float,float,float,float] | None`

- [ ] **Step 1: Завести git-репозиторий**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git init
git add -A
git commit -m "chore: исходное состояние фермы"
```

- [ ] **Step 2: Добавить pytest**

В `requirements.txt` дописать последней строкой:

```
pytest>=8.0
```

Установить:

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
.venv/bin/pip install -r requirements.txt
```

- [ ] **Step 3: Написать падающий тест разбора bounds**

Создать `tests/test_inspect.py`:

```python
"""Тесты разбора UI-дампа. Устройство не нужно: на входе строки."""
import pytest

from farm import inspect as uitree


def test_parse_bounds_переводит_пиксели_в_доли():
    assert uitree.parse_bounds("[0,0][610,1356]", 1220, 2712) == (0.0, 0.0, 0.5, 0.5)


def test_parse_bounds_зажимает_вылет_за_экран():
    # split-screen и вырезы дают координаты за пределами экрана
    assert uitree.parse_bounds("[-40,0][2000,4000]", 1220, 2712) == (0.0, 0.0, 1.0, 1.0)


def test_parse_bounds_отвергает_нулевую_площадь():
    assert uitree.parse_bounds("[10,10][10,90]", 1220, 2712) is None
    assert uitree.parse_bounds("[10,10][90,10]", 1220, 2712) is None


def test_parse_bounds_отвергает_мусор():
    assert uitree.parse_bounds(None, 1220, 2712) is None
    assert uitree.parse_bounds("", 1220, 2712) is None
    assert uitree.parse_bounds("[0,0]", 1220, 2712) is None
```

- [ ] **Step 4: Убедиться, что тест падает**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'farm.inspect'`

- [ ] **Step 5: Написать модуль с разбором bounds**

Создать `farm/inspect.py`:

```python
"""Разбор XML-дампа UI в узлы с готовыми селекторами.

Модуль намеренно не знает про adb: на входе строка XML и размер экрана,
на выходе плоский список узлов. Поэтому вся логика выбора селектора
проверяется тестами без устройства.

Имя модуля перекрывает стандартный `inspect` только внутри пакета `farm`
(в Python 3 импорты абсолютные), поэтому обращаться к нему следует как
`from . import inspect as uitree`.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Ограничители автоподъёма к clickable-предку
MAX_LIFT_LEVELS = 4        # дальше почти всегда контейнер, а не кнопка
MAX_LIFT_AREA_RATIO = 4.0  # центр предка уже не там, куда кликнули
ROOT_AREA = 0.95           # предок размером с экран — это корень

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


class InspectError(RuntimeError):
    """Дамп не удалось разобрать. Наверх уходит как понятный текст, не трейсбек."""


@dataclass
class Node:
    id: int
    parent: int | None
    bounds: tuple[float, float, float, float]  # доли 0..1: x1, y1, x2, y2
    text: str
    resource_id: str
    description: str
    cls: str
    clickable: bool
    children: list[int] = field(default_factory=list)

    @property
    def area(self) -> float:
        return (self.bounds[2] - self.bounds[0]) * (self.bounds[3] - self.bounds[1])


def _clamp(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def parse_bounds(raw, width: int, height: int):
    """`[x1,y1][x2,y2]` в пикселях → доли 0..1. None, если рамка негодная."""
    match = _BOUNDS_RE.fullmatch(raw or "")
    if match is None:
        return None
    x1, y1, x2, y2 = (int(v) for v in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return (
        _clamp(x1 / width), _clamp(y1 / height),
        _clamp(x2 / width), _clamp(y2 / height),
    )
```

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: PASS, 4 passed

- [ ] **Step 7: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add farm/inspect.py tests/test_inspect.py requirements.txt
git commit -m "feat: разбор bounds UI-дампа в доли экрана"
```

---

### Task 2: Разбор XML в плоский список узлов

**Files:**
- Modify: `farm/inspect.py`
- Modify: `tests/test_inspect.py`

**Interfaces:**
- Consumes: `Node`, `parse_bounds`, `InspectError` из Task 1
- Produces: `parse(xml: str, width: int, height: int) -> list[Node]`. Гарантирует `nodes[i].id == i` и заполненные `parent` / `children`

- [ ] **Step 1: Написать падающие тесты разбора**

Дописать в `tests/test_inspect.py` (сверху, после `import`, добавить фикстуры):

```python
# Дамп в формате uiautomator. Классический экран на View: кнопка с resource-id.
VIEWS_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" package="com.app" text=""
        resource-id="" content-desc="" clickable="false" bounds="[0,0][1220,2712]">
    <node index="0" class="android.widget.Button" package="com.app" text="Войти"
          resource-id="com.app:id/login_btn" content-desc="" clickable="true"
          bounds="[40,820][680,940]" />
    <node index="1" class="android.widget.TextView" package="com.app" text="Войти"
          resource-id="" content-desc="" clickable="false"
          bounds="[40,1000][680,1060]" />
    <node index="2" class="android.widget.TextView" package="com.app" text="Войти"
          resource-id="" content-desc="" clickable="false"
          bounds="[40,1100][680,1160]" />
  </node>
</hierarchy>
"""

# Compose: resource-id пуст везде, класс generic, clickable на родителе.
COMPOSE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" package="com.app" text=""
        resource-id="" content-desc="" clickable="false" bounds="[0,0][1220,2712]">
    <node index="0" class="android.view.View" package="com.app" text=""
          resource-id="" content-desc="" clickable="true"
          bounds="[40,820][680,940]">
      <node index="0" class="android.view.View" package="com.app" text="Войти"
            resource-id="" content-desc="" clickable="false"
            bounds="[60,850][660,910]" />
    </node>
  </node>
</hierarchy>
"""


def test_parse_нумерует_узлы_подряд():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    assert [n.id for n in nodes] == list(range(len(nodes)))


def test_parse_собирает_атрибуты_и_родителей():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    root, button = nodes[0], nodes[1]
    assert root.parent is None
    assert button.parent == 0
    assert root.children == [1, 2, 3]
    assert button.text == "Войти"
    assert button.resource_id == "com.app:id/login_btn"
    assert button.cls == "android.widget.Button"
    assert button.clickable is True


def test_parse_пропускает_узлы_без_годных_bounds():
    xml = """<hierarchy>
      <node class="A" bounds="[0,0][0,0]">
        <node class="B" text="видимый" bounds="[10,10][100,100]" />
      </node>
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    # родитель нулевой площади выброшен, ребёнок подцеплен на его место
    assert len(nodes) == 1
    assert nodes[0].cls == "B"
    assert nodes[0].parent is None


def test_parse_битый_xml_даёт_InspectError():
    with pytest.raises(uitree.InspectError):
        uitree.parse("<hierarchy><node", 1220, 2712)


def test_parse_нулевой_размер_экрана_даёт_InspectError():
    with pytest.raises(uitree.InspectError):
        uitree.parse(VIEWS_XML, 0, 2712)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: FAIL — `AttributeError: module 'farm.inspect' has no attribute 'parse'`

- [ ] **Step 3: Реализовать parse**

Дописать в конец `farm/inspect.py`:

```python
def parse(xml: str, width: int, height: int) -> list[Node]:
    """XML-дамп uiautomator → плоский список узлов. `nodes[i].id == i`.

    Узлы с негодными рамками выбрасываются, а их дети подцепляются к
    ближайшему уцелевшему предку: кликнуть по узлу нулевой площади нельзя,
    но его содержимое вполне кликабельно.
    """
    if width <= 0 or height <= 0:
        raise InspectError(f"некорректный размер экрана: {width}x{height}")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise InspectError(f"не удалось разобрать XML-дамп: {e}") from e

    nodes: list[Node] = []

    def walk(element, parent_id: int | None) -> None:
        bounds = parse_bounds(element.get("bounds"), width, height)
        own_id = parent_id
        if bounds is not None:
            own_id = len(nodes)
            nodes.append(Node(
                id=own_id,
                parent=parent_id,
                bounds=bounds,
                text=(element.get("text") or "").strip(),
                resource_id=(element.get("resource-id") or "").strip(),
                description=(element.get("content-desc") or "").strip(),
                cls=(element.get("class") or "").strip(),
                clickable=element.get("clickable") == "true",
            ))
            if parent_id is not None:
                nodes[parent_id].children.append(own_id)
        for child in element:
            walk(child, own_id)

    walk(root, None)
    return nodes
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add farm/inspect.py tests/test_inspect.py
git commit -m "feat: разбор XML-дампа в плоский список узлов"
```

---

### Task 3: Выбор узла по точке и автоподъём к clickable-предку

**Files:**
- Modify: `farm/inspect.py`
- Modify: `tests/test_inspect.py`

**Interfaces:**
- Consumes: `Node`, `parse` из Task 2
- Produces: `node_at(nodes: list[Node], x: float, y: float) -> Node | None`, `resolve_target(nodes: list[Node], node: Node) -> tuple[Node, int]` (узел и число пройденных уровней)

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_inspect.py`:

```python
def test_node_at_берёт_наименьший_узел_под_точкой():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    # точка внутри кнопки, которая лежит внутри корневого FrameLayout
    hit = uitree.node_at(nodes, 360 / 1220, 880 / 2712)
    assert hit.resource_id == "com.app:id/login_btn"


def test_node_at_вне_экрана_даёт_None():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    assert uitree.node_at(nodes, 0.5, 0.999) is not None  # внутри корня
    assert uitree.node_at(nodes, 1.5, 0.5) is None


def test_resolve_target_кликабельный_узел_остаётся_собой():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    button = nodes[1]
    assert uitree.resolve_target(nodes, button) == (button, 0)


def test_resolve_target_поднимается_к_clickable_предку_в_compose():
    nodes = uitree.parse(COMPOSE_XML, 1220, 2712)
    text_node = uitree.node_at(nodes, 360 / 1220, 880 / 2712)
    assert text_node.text == "Войти"
    assert text_node.clickable is False
    # у предка нет resourceId и description, значит подниматься смысла нет:
    # центр-тап по ребёнку и так попадёт в родителя
    target, lift = uitree.resolve_target(nodes, text_node)
    assert (target, lift) == (text_node, 0)


def test_resolve_target_поднимается_если_предок_даёт_идентификатор():
    xml = """<hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1220,2712]">
        <node class="android.view.View" resource-id="com.app:id/card"
              clickable="true" bounds="[40,820][680,940]">
          <node class="android.view.View" text="Войти" clickable="false"
                bounds="[60,850][660,910]" />
        </node>
      </node>
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    child = uitree.node_at(nodes, 360 / 1220, 880 / 2712)
    target, lift = uitree.resolve_target(nodes, child)
    assert target.resource_id == "com.app:id/card"
    assert lift == 1


def test_resolve_target_не_поднимается_к_слишком_большому_предку():
    # предок в 10 раз больше ребёнка: центр уедет с кнопки
    xml = """<hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1220,2712]">
        <node class="android.view.View" resource-id="com.app:id/row"
              clickable="true" bounds="[0,800][1220,1400]">
          <node class="android.view.View" text="Войти" clickable="false"
                bounds="[40,820][240,880]" />
        </node>
      </node>
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    child = uitree.node_at(nodes, 100 / 1220, 850 / 2712)
    target, lift = uitree.resolve_target(nodes, child)
    assert (target, lift) == (child, 0)


def test_resolve_target_не_поднимается_к_корню():
    xml = """<hierarchy>
      <node class="android.widget.FrameLayout" resource-id="com.app:id/root"
            clickable="true" bounds="[0,0][1220,2712]">
        <node class="android.view.View" text="Войти" clickable="false"
              bounds="[0,0][1220,2600]" />
      </node>
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    child = nodes[1]
    target, lift = uitree.resolve_target(nodes, child)
    assert (target, lift) == (child, 0)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: FAIL — `AttributeError: module 'farm.inspect' has no attribute 'node_at'`

- [ ] **Step 3: Реализовать выбор и подъём**

Дописать в конец `farm/inspect.py`:

```python
def node_at(nodes: list[Node], x: float, y: float) -> Node | None:
    """Наименьший по площади узел, накрывающий точку. Доли 0..1."""
    best: Node | None = None
    for node in nodes:
        x1, y1, x2, y2 = node.bounds
        if x < x1 or x > x2 or y < y1 or y > y2:
            continue
        if best is None or node.area < best.area:
            best = node
    return best


def resolve_target(nodes: list[Node], node: Node) -> tuple[Node, int]:
    """Узел, по которому строить селектор, и сколько уровней вверх прошли.

    `el.click()` в uiautomator2 тапает по центру bounds, а не дёргает
    performAction(CLICK). Поэтому clickable=false тап не ломает: касание
    прилетает в ту же точку, и Android отдаёт его родителю. Подниматься
    имеет смысл только ради лучшего селектора и только пока центр предка
    остаётся там же, куда кликнули.
    """
    if node.clickable:
        return node, 0
    current = node
    for level in range(1, MAX_LIFT_LEVELS + 1):
        if current.parent is None:
            break
        parent = nodes[current.parent]
        if parent.area > node.area * MAX_LIFT_AREA_RATIO:
            break
        if parent.area >= ROOT_AREA:
            break
        current = parent
        if current.clickable:
            if current.resource_id or current.description:
                return current, level
            break
    return node, 0
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: PASS, 16 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add farm/inspect.py tests/test_inspect.py
git commit -m "feat: выбор узла по точке и автоподъём к clickable-предку"
```

---

### Task 4: Построение селекторов и подсчёт уникальности

**Files:**
- Modify: `farm/inspect.py`
- Modify: `tests/test_inspect.py`

**Interfaces:**
- Consumes: `Node`, `parse`, `resolve_target` из Task 3
- Produces: `build_selectors(nodes: list[Node], node: Node) -> list[dict]`. Каждый словарь: `{"call": "click"|"tap", "args": str, "matches": int, "fragile": bool}`. Отсортирован от надёжного к хрупкому

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_inspect.py`:

```python
def test_build_selectors_resourceId_идёт_первым():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    sels = uitree.build_selectors(nodes, nodes[1])
    assert sels[0]["call"] == "click"
    assert sels[0]["args"] == 'resourceId="com.app:id/login_btn"'
    assert sels[0]["matches"] == 1
    assert sels[0]["fragile"] is False


def test_build_selectors_считает_совпадения_по_тексту():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    # «Войти» встречается на кнопке и двух TextView
    sels = uitree.build_selectors(nodes, nodes[1])
    by_text = [s for s in sels if s["args"] == 'text="Войти"']
    assert by_text[0]["matches"] == 3


def test_build_selectors_пропускает_пустые_атрибуты():
    nodes = uitree.parse(COMPOSE_XML, 1220, 2712)
    text_node = [n for n in nodes if n.text == "Войти"][0]
    sels = uitree.build_selectors(nodes, text_node)
    # resourceId и description пусты — в кандидаты не попали
    assert all("resourceId" not in s["args"] for s in sels)
    assert all("description" not in s["args"] for s in sels)
    assert sels[0]["args"] == 'text="Войти"'
    assert sels[0]["matches"] == 1


def test_build_selectors_уникальные_поднимаются_выше_неуникальных():
    xml = """<hierarchy>
      <node class="android.widget.Button" text="Войти" content-desc="Вход"
            resource-id="" clickable="true" bounds="[40,820][680,940]" />
      <node class="android.widget.TextView" text="Войти" content-desc=""
            resource-id="" clickable="false" bounds="[40,1000][680,1060]" />
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    sels = uitree.build_selectors(nodes, nodes[0])
    # description уникален, text — нет, значит description впереди
    assert sels[0]["args"] == 'description="Вход"'
    assert sels[0]["matches"] == 1
    assert sels[1]["args"] == 'text="Войти"'
    assert sels[1]["matches"] == 2


def test_build_selectors_добавляет_комбинацию_и_instance_если_уникальных_нет():
    xml = """<hierarchy>
      <node class="android.widget.TextView" text="Войти" content-desc=""
            resource-id="" clickable="false" bounds="[40,820][680,880]" />
      <node class="android.widget.TextView" text="Войти" content-desc=""
            resource-id="" clickable="false" bounds="[40,900][680,960]" />
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    sels = uitree.build_selectors(nodes, nodes[1])
    args = [s["args"] for s in sels]
    assert 'text="Войти", className="android.widget.TextView"' in args
    assert 'className="android.widget.TextView", instance=1' in args
    instance_sel = [s for s in sels if "instance=" in s["args"]][0]
    assert instance_sel["matches"] == 1
    assert instance_sel["fragile"] is True


def test_build_selectors_без_идентификаторов_даёт_tap_по_координатам():
    xml = """<hierarchy>
      <node class="" text="" content-desc="" resource-id=""
            clickable="true" bounds="[0,0][610,1356]" />
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    sels = uitree.build_selectors(nodes, nodes[0])
    assert sels == [{"call": "tap", "args": "0.25, 0.25", "matches": 1, "fragile": True}]


def test_build_selectors_экранирует_кавычки_в_тексте():
    xml = """<hierarchy>
      <node class="android.widget.TextView" text='Нажми &quot;тут&quot;'
            content-desc="" resource-id="" clickable="false"
            bounds="[40,820][680,880]" />
    </hierarchy>"""
    nodes = uitree.parse(xml, 1220, 2712)
    sels = uitree.build_selectors(nodes, nodes[0])
    assert sels[0]["args"] == 'text="Нажми \\"тут\\""'
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: FAIL — `AttributeError: module 'farm.inspect' has no attribute 'build_selectors'`

- [ ] **Step 3: Реализовать построение селекторов**

Дописать в конец `farm/inspect.py`:

```python
# Порядок важен: чем выше, тем устойчивее селектор к правкам приложения.
# resourceId переживает смену языка, description задан разработчиком явно,
# text ломается от локализации — но на Compose часто единственный доступный.
_PRIORITY = ("resourceId", "description", "text")


def _attr(node: Node, key: str) -> str:
    if key == "resourceId":
        return node.resource_id
    if key == "description":
        return node.description
    return node.text


def _literal(value: str) -> str:
    """Строка в виде python-литерала: то, что можно вставить в сценарий."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_selectors(nodes: list[Node], node: Node) -> list[dict]:
    """Кандидаты-селекторы для узла, от самого надёжного к самому хрупкому.

    `matches` — сколько узлов дампа удовлетворяют этому селектору. Сравнение
    точным равенством строки, как это делает uiautomator2. Единица означает,
    что селектор однозначен на текущем экране.
    """
    out: list[dict] = []
    for key in _PRIORITY:
        value = _attr(node, key)
        if not value:
            continue
        out.append({
            "call": "click",
            "args": f"{key}={_literal(value)}",
            "matches": sum(1 for n in nodes if _attr(n, key) == value),
            "fragile": False,
        })

    if out and not any(s["matches"] == 1 for s in out) and node.cls:
        for key in _PRIORITY:
            value = _attr(node, key)
            if not value:
                continue
            out.append({
                "call": "click",
                "args": f"{key}={_literal(value)}, className={_literal(node.cls)}",
                "matches": sum(1 for n in nodes
                               if _attr(n, key) == value and n.cls == node.cls),
                "fragile": True,
            })
        same_class = [n.id for n in nodes if n.cls == node.cls]
        out.append({
            "call": "click",
            "args": f"className={_literal(node.cls)}, instance={same_class.index(node.id)}",
            "matches": 1,   # instance уникален по определению, но хрупок к перевёрстке
            "fragile": True,
        })

    if not out:
        cx = round((node.bounds[0] + node.bounds[2]) / 2, 3)
        cy = round((node.bounds[1] + node.bounds[3]) / 2, 3)
        return [{"call": "tap", "args": f"{cx}, {cy}", "matches": 1, "fragile": True}]

    # sort устойчив: внутри групп сохраняется приоритет атрибутов
    out.sort(key=lambda s: (s["matches"] != 1, s["fragile"]))
    return out
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: PASS, 23 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add farm/inspect.py tests/test_inspect.py
git commit -m "feat: построение селекторов с подсчётом уникальности"
```

---

### Task 5: Сборка ответа и эндпоинт

**Files:**
- Modify: `farm/inspect.py`
- Modify: `farm/server.py` (после ручки `hierarchy`, строка ~119)
- Modify: `tests/test_inspect.py`

**Interfaces:**
- Consumes: `parse`, `node_at`, `resolve_target`, `build_selectors` из Task 4
- Produces: `to_payload(nodes: list[Node]) -> list[dict]`; эндпоинт `GET /api/devices/{serial}/inspect`

- [ ] **Step 1: Написать падающий тест сборки ответа**

Дописать в `tests/test_inspect.py`:

```python
def test_to_payload_отдаёт_плоский_список_с_селекторами():
    nodes = uitree.parse(VIEWS_XML, 1220, 2712)
    payload = uitree.to_payload(nodes)
    assert [n["id"] for n in payload] == list(range(len(nodes)))
    button = payload[1]
    assert button["resourceId"] == "com.app:id/login_btn"
    assert button["class"] == "android.widget.Button"
    assert button["clickable"] is True
    assert button["target"] == 1        # сам кликабелен, подъёма нет
    assert button["lift"] == 0
    assert button["bounds"] == [pytest.approx(40 / 1220), pytest.approx(820 / 2712),
                                pytest.approx(680 / 1220), pytest.approx(940 / 2712)]
    assert button["selectors"][0]["args"] == 'resourceId="com.app:id/login_btn"'


def test_to_payload_проставляет_target_на_clickable_предка():
    xml = """<hierarchy>
      <node class="android.widget.FrameLayout" bounds="[0,0][1220,2712]">
        <node class="android.view.View" resource-id="com.app:id/card"
              clickable="true" bounds="[40,820][680,940]">
          <node class="android.view.View" text="Войти" clickable="false"
                bounds="[60,850][660,910]" />
        </node>
      </node>
    </hierarchy>"""
    payload = uitree.to_payload(uitree.parse(xml, 1220, 2712))
    child = payload[2]
    assert child["target"] == 1
    assert child["lift"] == 1
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: FAIL — `AttributeError: module 'farm.inspect' has no attribute 'to_payload'`

- [ ] **Step 3: Реализовать to_payload**

Дописать в конец `farm/inspect.py`:

```python
def to_payload(nodes: list[Node]) -> list[dict]:
    """Узлы в JSON-виде для фронта.

    Селекторы и цель подъёма считаются здесь, а не в браузере: логика должна
    жить рядом с `ctx.click(**selector)` из farm/context.py, иначе стороны
    разъедутся. Фронт остаётся тупым — только попадание мышью и отрисовка.
    """
    out = []
    for node in nodes:
        target, lift = resolve_target(nodes, node)
        out.append({
            "id": node.id,
            "parent": node.parent,
            "bounds": list(node.bounds),
            "text": node.text,
            "resourceId": node.resource_id,
            "description": node.description,
            "class": node.cls,
            "clickable": node.clickable,
            "target": target.id,
            "lift": lift,
            "selectors": build_selectors(nodes, target),
        })
    return out
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/test_inspect.py -v`
Expected: PASS, 25 passed

- [ ] **Step 5: Добавить эндпоинт**

В `farm/server.py` в шапку файла, к остальным `import`, добавить:

```python
import base64
```

и в блок импортов пакета добавить `inspect as uitree`, например:

```python
from . import adb, config, control, screen
from . import inspect as uitree
```

Сразу после функции `hierarchy` (она заканчивается на `raise HTTPException(500, str(e))`) вставить:

```python
@app.get("/api/devices/{serial}/inspect")
def inspect_screen(serial: str):
    """Снимок экрана и разобранная иерархия одним ответом.

    Атомарность важна: если тянуть картинку и дамп разными запросами, между
    ними экран успевает смениться, и рамки лягут мимо элементов.
    """
    try:
        xml = control.dump_hierarchy(serial)
        shot = control.screenshot(serial, max_width=config.ARTIFACT_MAX_WIDTH, quality=85)
        width, height = control.size(serial)
        nodes = uitree.parse(xml, width, height)
    except uitree.InspectError as e:
        raise HTTPException(500, str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"не удалось снять экран: {e}")
    return {
        "width": width,
        "height": height,
        "screenshot": "data:image/jpeg;base64," + base64.b64encode(shot).decode("ascii"),
        "nodes": uitree.to_payload(nodes),
    }
```

- [ ] **Step 6: Проверить эндпоинт вживую**

Запустить ферму (`./run.sh`), затем в другом терминале:

```bash
curl -s "http://127.0.0.1:8777/api/devices/79AULJHYVCKRKF5L/inspect" \
  | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print('узлов:', len(d['nodes'])); print('экран:', d['width'], 'x', d['height']); print('кадр, КБ:', len(d['screenshot'])//1024); print(json.dumps(d['nodes'][:2], ensure_ascii=False, indent=2))"
```

Expected: узлов больше нуля, размер экрана совпадает с реальным, у узлов заполнены `selectors`.

- [ ] **Step 7: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add farm/inspect.py farm/server.py tests/test_inspect.py
git commit -m "feat: эндпоинт /inspect — кадр и иерархия одним ответом"
```

---

### Task 6: Оверлей на фронте — разметка, стили, замороженный кадр

**Files:**
- Create: `static/inspector.js`
- Modify: `static/index.html` (стили ~строка 160, шапка экрана ~302, `.stage` ~307, `startStream` ~688, `setActive` ~596, подключение скрипта в конце)

**Interfaces:**
- Consumes: `GET /api/devices/{serial}/inspect` из Task 5; хелперы `$`, `api`, `toast`, объект `S`, функция `startStream` из `index.html`
- Produces: глобальные `INSP` (состояние), `toggleInspector()`, `inspectorOff()`, `inspRender()`, `inspSyncRect()`

- [ ] **Step 1: Добавить стили оверлея**

В `static/index.html` в блок `<style>`, сразу после правила `#screen.dead{...}`, вставить:

```css
  /* --- оверлей инспектора --- */
  .stage{position:relative}
  #inspLayer{position:absolute;display:none;pointer-events:auto;cursor:crosshair;border-radius:20px;overflow:hidden}
  .ib{position:absolute;border:1px solid rgba(61,220,132,.28);box-sizing:border-box;pointer-events:none}
  .ib.hov{border-color:rgba(61,220,132,.95);background:rgba(61,220,132,.12)}
  .ib.sel{border:2px solid var(--accent);background:rgba(61,220,132,.2)}
  #btnInsp.on{color:var(--accent);border-color:var(--accent)}
  .selbox{font:12px var(--mono);line-height:1.7}
  .selbox .sel-main{background:#0d1117;border:1px solid var(--line);border-radius:6px;padding:8px;
    word-break:break-all;color:var(--accent);margin-bottom:6px}
  .selbox .sel-alt{color:var(--dim);word-break:break-all}
  .selbox .ok{color:var(--ok)}
  .selbox .warn{color:var(--warn)}
  .selbox table{width:100%;border-collapse:collapse;margin-top:8px}
  .selbox td{padding:2px 4px;vertical-align:top;border-top:1px solid var(--line)}
  .selbox td:first-child{color:var(--dim);width:88px}
```

- [ ] **Step 2: Добавить кнопки и слой в разметку**

В `static/index.html` в шапке колонки экрана, после кнопки `scrcpy`, добавить две кнопки:

```html
      <button class="sm" onclick="toggleInspector()" id="btnInsp">🔍 инспектор</button>
      <button class="sm" onclick="inspectorReload()" id="btnInspReload" style="display:none">⟳ обновить</button>
```

Внутри `<div class="stage">`, сразу после `<img id="screen" alt="">`, добавить:

```html
      <div id="inspLayer"></div>
```

Перед закрывающим `</script>` в конце файла (после строки `setInterval(loadScenarios, 15000);`) ничего не меняем, а **после** тега `</script>` добавить:

```html
<script src="/static/inspector.js"></script>
```

- [ ] **Step 3: Научить startStream показывать замороженный кадр**

В `static/index.html` в функции `startStream` заменить блок присвоения `img.src`:

```js
  img.src = S.streaming
    ? `/api/devices/${S.active}/stream?t=${Date.now()}`
    : `/api/devices/${S.active}/frame?t=${Date.now()}`;
```

на:

```js
  // Инспектор работает по замороженному кадру: рамки и картинка обязаны быть
  // из одного снимка, иначе рамки лягут мимо элементов.
  img.onload = () => { if(window.inspSyncRect) inspSyncRect(); };
  img.src = (window.INSP && INSP.on && INSP.data)
    ? INSP.data.screenshot
    : S.streaming
      ? `/api/devices/${S.active}/stream?t=${Date.now()}`
      : `/api/devices/${S.active}/frame?t=${Date.now()}`;
```

- [ ] **Step 4: Сбрасывать инспектор при смене устройства**

В `static/index.html` в функции `setActive` добавить сброс перед `startStream()`:

```js
function setActive(serial){
  if(S.active === serial) return;
  S.active = serial;
  const d = S.devices.find(x => x.serial === serial);
  $('scrTitle').textContent = d ? d.name : 'Экран';
  markActive();
  if(window.inspectorOff) inspectorOff();   // рамки от чужого экрана хуже, чем их отсутствие
  startStream();
}
```

- [ ] **Step 5: Написать inspector.js**

Создать `static/inspector.js`:

```js
/* Визуальный инспектор UI.
   Логика селекторов живёт на сервере (farm/inspect.py) — здесь только
   заморозка кадра, попадание мышью по узлам и отрисовка. */

const INSP = {
  on: false,
  data: null,
  nodes: [],
  hover: null,     // id узла под курсором
  sel: null,       // id выбранного узла
  all: false,      // показывать узлы без идентификаторов
  prevStreaming: true,
};

async function toggleInspector(){
  if(INSP.on){ inspectorOff(); return; }
  if(!S.active){ toast('сначала выберите устройство', 'bad'); return; }
  INSP.prevStreaming = S.streaming;
  await inspectorLoad();
}

async function inspectorReload(){
  if(INSP.on) await inspectorLoad();
}

async function inspectorLoad(){
  const btn = $('btnInsp');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'снимаю…';
  try{
    const data = await api(`/api/devices/${S.active}/inspect`);
    INSP.data = data;
    INSP.nodes = data.nodes || [];
    INSP.on = true;
    INSP.hover = null;
    INSP.sel = null;
    S.streaming = false;
    $('btnStream').textContent = 'смотреть';
    btn.classList.add('on');
    btn.textContent = '🔍 инспектор ✓';
    $('btnInspReload').style.display = '';
    $('inspLayer').style.display = 'block';
    startStream();          // подставит INSP.data.screenshot
    inspRender();
    if(window.inspPanel) inspPanel();   // панель появляется в Task 7
    if(!INSP.nodes.length) toast('на экране не распознано ни одного узла', 'bad');
  }catch(e){
    toast(e.message, 'bad');
    btn.textContent = label;
    inspectorOff();
  }finally{
    btn.disabled = false;
  }
}

function inspectorOff(){
  const wasOn = INSP.on;
  INSP.on = false;
  INSP.data = null;
  INSP.nodes = [];
  INSP.hover = null;
  INSP.sel = null;
  const layer = $('inspLayer');
  if(layer){ layer.style.display = 'none'; layer.innerHTML = ''; }
  const btn = $('btnInsp');
  if(btn){ btn.classList.remove('on'); btn.textContent = '🔍 инспектор'; }
  const reload = $('btnInspReload');
  if(reload) reload.style.display = 'none';
  if(window.inspPanel) inspPanel();   // панель появляется в Task 7
  if(wasOn){
    S.streaming = INSP.prevStreaming;
    $('btnStream').textContent = S.streaming ? 'пауза' : 'смотреть';
    startStream();
  }
}

/* Слой позиционируется по реальному прямоугольнику картинки: #screen центрируется
   во flex-контейнере и ужат max-width/max-height, поэтому он меньше .stage. */
function inspSyncRect(){
  const layer = $('inspLayer'), img = $('screen');
  if(!layer || !img || !INSP.on) return;
  const s = img.getBoundingClientRect();
  const st = img.parentElement.getBoundingClientRect();
  layer.style.left = (s.left - st.left) + 'px';
  layer.style.top = (s.top - st.top) + 'px';
  layer.style.width = s.width + 'px';
  layer.style.height = s.height + 'px';
}

function inspRender(){
  const layer = $('inspLayer');
  if(!layer) return;
  if(!INSP.on){ layer.innerHTML = ''; return; }
  inspSyncRect();
  const parts = [];
  for(const n of INSP.nodes){
    const named = n.text || n.resourceId || n.description;
    if(!INSP.all && !named) continue;
    const [x1, y1, x2, y2] = n.bounds;
    let cls = 'ib';
    if(INSP.sel === n.id) cls += ' sel';
    else if(INSP.hover === n.id) cls += ' hov';
    parts.push(`<div class="${cls}" style="left:${x1*100}%;top:${y1*100}%;`
             + `width:${(x2-x1)*100}%;height:${(y2-y1)*100}%"></div>`);
  }
  layer.innerHTML = parts.join('');
}

/* Наименьший по площади узел под курсором — тот же критерий, что на сервере. */
function inspHit(ev){
  const layer = $('inspLayer');
  const r = layer.getBoundingClientRect();
  if(!r.width || !r.height) return null;
  const x = (ev.clientX - r.left) / r.width;
  const y = (ev.clientY - r.top) / r.height;
  let best = null, bestArea = Infinity;
  for(const n of INSP.nodes){
    const [x1, y1, x2, y2] = n.bounds;
    if(x < x1 || x > x2 || y < y1 || y > y2) continue;
    const area = (x2 - x1) * (y2 - y1);
    if(area < bestArea){ bestArea = area; best = n; }
  }
  return best;
}

(function(){
  const layer = document.getElementById('inspLayer');
  if(!layer) return;

  layer.addEventListener('mousemove', ev => {
    if(!INSP.on) return;
    const hit = inspHit(ev);
    const id = hit ? hit.id : null;
    if(id !== INSP.hover){ INSP.hover = id; inspRender(); }
  });

  layer.addEventListener('mouseleave', () => {
    if(INSP.on && INSP.hover !== null){ INSP.hover = null; inspRender(); }
  });

  layer.addEventListener('click', ev => {
    if(!INSP.on) return;
    const hit = inspHit(ev);
    INSP.sel = hit ? hit.id : null;
    inspRender();
    inspPanel();
  });

  // Сцена меняет размер и без ресайза окна — например при переключении
  // вкладок в правой колонке. Одного window.resize недостаточно.
  const stage = layer.parentElement;
  if(stage && window.ResizeObserver){
    new ResizeObserver(inspSyncRect).observe(stage);
  }
  window.addEventListener('resize', inspSyncRect);
})();
```

- [ ] **Step 6: Проверить оверлей в браузере**

Запустить ферму (`./run.sh`), открыть `http://127.0.0.1:8777`, выбрать устройство, нажать «🔍 инспектор».

Expected:
- кадр замирает, кнопка «пауза» переключается в «смотреть»;
- поверх картинки видны тонкие рамки на элементах с текстом или id;
- под курсором рамка подсвечивается ярче;
- клик по элементу подсвечивает его акцентным цветом и **не тапает устройство** (экран не реагирует);
- «⟳ обновить» пересниимает кадр;
- повторное нажатие «🔍 инспектор» убирает рамки и возвращает стрим;
- переключение устройства сбрасывает инспектор.

На этом шаге панель справа ещё пустая — она делается в Task 7. В консоли браузера ошибок быть не должно.

- [ ] **Step 7: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add static/inspector.js static/index.html
git commit -m "feat: оверлей инспектора поверх замороженного кадра"
```

---

### Task 7: Панель выбранного элемента

**Files:**
- Modify: `static/inspector.js`
- Modify: `static/index.html` (блок `#pane-insp`, ~строка 373)

**Interfaces:**
- Consumes: `INSP`, `inspRender` из Task 6
- Produces: `inspPanel()`, `inspCopy(index)`, `inspToggleAll(checked)`

- [ ] **Step 1: Добавить блок панели в разметку**

В `static/index.html` внутри `<div class="pane" id="pane-insp">`, **перед** блоком `<div class="box"><h3>Запуск приложения</h3>`, вставить:

```html
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
```

- [ ] **Step 2: Реализовать панель**

Дописать в конец `static/inspector.js`:

```js
function inspEsc(s){
  return String(s).replace(/[&<>"]/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]
  ));
}

function inspToggleAll(checked){
  INSP.all = !!checked;
  inspRender();
}

function inspPanel(){
  const box = $('inspSel');
  if(!box) return;
  if(!INSP.on){
    box.innerHTML = '<div class="empty">Включите инспектор и ткните в элемент.</div>';
    return;
  }
  if(!INSP.nodes.length){
    box.innerHTML = '<div class="empty">Ничего не распознано.<br>'
      + 'WebView, SurfaceView и игры не отдают узлы<br>через accessibility — '
      + 'это ограничение Android,<br>а не сбой фермы.</div>';
    return;
  }
  if(INSP.sel === null){
    box.innerHTML = '<div class="empty">Ткните в элемент на экране.</div>';
    return;
  }

  const clicked = INSP.nodes[INSP.sel];
  const node = INSP.nodes[clicked.target];
  const sels = node.selectors || [];
  const parts = [];

  if(clicked.target !== clicked.id){
    parts.push(`<div class="sel-alt">↑ выбран clickable-предок (${clicked.lift})</div>`);
  }else if(!node.clickable){
    parts.push('<div class="sel-alt">узел не clickable — тап по центру сработает</div>');
  }

  if(sels.length){
    const best = sels[0];
    const mark = best.matches === 1
      ? '<span class="ok">✓ уникален на экране</span>'
      : `<span class="warn">⚠ совпадений: ${best.matches}</span>`;
    parts.push(
      `<div class="sel-main">ctx.${best.call}(${inspEsc(best.args)})</div>`
      + `<div>${mark} <button class="sm" onclick="inspCopy(0)">⧉ копировать</button></div>`
    );
    if(sels.length > 1){
      parts.push('<div class="sel-alt" style="margin-top:8px">альтернативы:</div>');
      sels.slice(1).forEach((s, i) => {
        const m = s.matches === 1
          ? '<span class="ok">✓</span>'
          : `<span class="warn">⚠${s.matches}</span>`;
        parts.push(
          `<div class="sel-alt">${m} ctx.${s.call}(${inspEsc(s.args)}) `
          + `<button class="sm" onclick="inspCopy(${i + 1})">⧉</button></div>`
        );
      });
    }
  }

  const rows = [
    ['class', node.class],
    ['resourceId', node.resourceId],
    ['text', node.text],
    ['description', node.description],
    ['clickable', String(node.clickable)],
    ['bounds', node.bounds.map(v => v.toFixed(3)).join(', ')],
  ].filter(([, v]) => v !== '');

  parts.push('<table>' + rows.map(
    ([k, v]) => `<tr><td>${k}</td><td>${inspEsc(v)}</td></tr>`
  ).join('') + '</table>');

  box.innerHTML = parts.join('');
}

async function inspCopy(index){
  const node = INSP.nodes[INSP.nodes[INSP.sel].target];
  const sel = (node.selectors || [])[index];
  if(!sel) return;
  const line = `ctx.${sel.call}(${sel.args})`;
  try{
    await navigator.clipboard.writeText(line);
    toast('скопировано', 'ok');
  }catch(e){
    toast('буфер недоступен: ' + line, 'bad');
  }
}
```

- [ ] **Step 3: Проверить панель в браузере**

Перезагрузить `http://127.0.0.1:8777`, включить инспектор, кликнуть по нескольким элементам.

Expected:
- у элемента с `resource-id` первой строкой идёт `ctx.click(resourceId="...")` с зелёной отметкой уникальности;
- у повторяющегося текста показывается `⚠ совпадений: N`;
- альтернативные селекторы перечислены ниже;
- таблица атрибутов заполнена, пустые строки не показываются;
- «⧉ копировать» кладёт строку в буфер, всплывает «скопировано»;
- галка «все узлы» добавляет рамки на контейнеры без идентификаторов;
- на Compose-экране (любое современное приложение) `resourceId` пуст, селектор строится по `text`.

- [ ] **Step 4: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add static/inspector.js static/index.html
git commit -m "feat: панель выбранного элемента с готовым селектором"
```

---

### Task 8: Проверка на реальном устройстве и заметка в README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: всё из Task 7
- Produces: ничего

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `cd /Users/hlamov.ilya/Desktop/android-farm && .venv/bin/python -m pytest tests/ -v`
Expected: PASS, 25 passed

- [ ] **Step 2: Проверить селектор в бою**

Снять селектор инспектором на реальном экране, вставить его в сценарий и убедиться, что элемент находится:

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
.venv/bin/python -c "
from farm import control
from farm import inspect as uitree
serial = '79AULJHYVCKRKF5L'
w, h = control.size(serial)
nodes = uitree.parse(control.dump_hierarchy(serial), w, h)
print('узлов:', len(nodes))
for n in uitree.to_payload(nodes)[:10]:
    if n['selectors']:
        s = n['selectors'][0]
        print(f\"ctx.{s['call']}({s['args']})  совпадений={s['matches']}\")
"
```

Expected: печатаются строки вида `ctx.click(resourceId="...")`, числа совпадений осмысленные.

**Замечание:** этот шаг не инжектит ввод — только `dump_hierarchy` и `size`, оба read-only. Он проходит и на устройствах, где `input tap/swipe` отклоняется с `SecurityException: ... INJECT_EVENTS` (HyperOS/MIUI без тумблера «USB-отладка (настройки безопасности)»).

- [ ] **Step 3: Описать инспектор в README**

В `README.md` добавить раздел:

```markdown
## Визуальный инспектор

Кнопка «🔍 инспектор» над экраном замораживает кадр и рисует поверх него рамки
элементов. Клик по элементу даёт готовую строку для сценария —
`ctx.click(resourceId="...")` — с проверкой, сколько узлов на экране подходят
под этот селектор. Единица означает, что селектор однозначен.

Клик в режиме инспектора **не тапает устройство**. Чтобы вернуть управление,
выключите инспектор.

Приоритет селекторов: `resourceId` → `description` → `text` → связка с
`className` → `instance` → координаты. Для приложений на Jetpack Compose
`resourceId` обычно пуст (нужен `Modifier.testTag` вместе с
`semantics { testTagsAsResourceId = true }` на стороне приложения), поэтому
селектор строится по `text` или `description`.

Узлов не будет вовсе у `WebView`, `SurfaceView` и игр — они не отдают дерево
через accessibility. Это ограничение Android, а не фермы.
```

- [ ] **Step 4: Commit**

```bash
cd /Users/hlamov.ilya/Desktop/android-farm
git add README.md
git commit -m "docs: описание визуального инспектора"
```

---

## Отступления от спеки

Зафиксировано осознанно, обсудить при желании:

1. **Фикстуры тестов — синтетические, а не снятые с устройства.** Спека
   обещала два реальных дампа. Написанные вручную XML-строки детерминированы,
   читаются вместе с тестом и не требуют устройства в CI. Проверка на реальных
   экранах вынесена в Task 8, шаг 2.
2. **`target` и `lift` считаются на сервере для каждого узла.** В спеке
   попадание мышью описано как клиентское, а подъём — как серверный. Чтобы
   логика не размазалась по двум языкам, сервер отдаёт готовый `target` для
   каждого узла; клиент только ищет узел под курсором и идёт по ссылке.
3. **Имя модуля `farm/inspect.py` перекрывает стандартный `inspect`.** В
   Python 3 импорты абсолютные, поэтому `import inspect` где угодно вне пакета
   даёт стандартный модуль. Внутри `farm/` обращаться только как
   `from . import inspect as uitree`.
