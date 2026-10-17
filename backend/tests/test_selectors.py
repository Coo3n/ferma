"""Кандидаты селекторов: textContains, спуск к потомку, запасной instance."""
from farm.ui.selectors import build_selectors, text_stem, to_payload
from farm.ui.tree import Node


def node(nid, text="", rid="", desc="", cls="android.widget.TextView"):
    return Node(id=nid, parent=None, bounds=(0.1, 0.1, 0.3, 0.2),
                text=text, resource_id=rid, description=desc, cls=cls,
                clickable=True)


def args_of(selectors):
    return [s["args"] for s in selectors]


def test_stem_срезает_счётчик_и_пунктуацию():
    assert text_stem("Корзина (3)") == "Корзина"
    assert text_stem("Скидка 50%") == "Скидка"
    assert text_stem("Войти") == "Войти"
    assert text_stem("12+") == ""


def test_текст_с_хвостом_даёт_вариант_textContains():
    target = node(0, text="Корзина (3)")
    result = build_selectors([target], target)
    assert 'textContains="Корзина"' in args_of(result)
    assert 'text="Корзина (3)"' in args_of(result)


def test_текст_без_хвоста_не_дублируется_в_textContains():
    target = node(0, text="Войти")
    result = build_selectors([target], target)
    assert not any("textContains" in a for a in args_of(result))


def test_плитка_без_подписи_получает_селектор_потомка():
    """Compose-паттерн: кликабельный контейнер пуст, подпись в потомке."""
    tile = Node(id=0, parent=None, bounds=(0.0, 0.4, 0.2, 0.55),
                text="", resource_id="", description="",
                cls="android.view.View", clickable=True, children=[1, 2])
    icon = Node(id=1, parent=0, bounds=(0.0, 0.4, 0.1, 0.55),
                text="", resource_id="", description="",
                cls="android.widget.ImageView", clickable=False)
    label = Node(id=2, parent=0, bounds=(0.1, 0.4, 0.2, 0.55),
                 text="Одежда", resource_id="", description="",
                 cls="android.widget.TextView", clickable=False)
    payload = to_payload([tile, icon, label])

    assert payload[0]["selectors"][0]["args"] == 'text="Одежда"'
    # клик по безымянной иконке поднимается в контейнер и берёт ту же подпись
    assert payload[1]["target"] == 0
    assert payload[1]["selectors"][0]["args"] == 'text="Одежда"'


def test_узел_совсем_без_подписей_даёт_instance_перед_координатами():
    lone = node(0)
    result = build_selectors([lone], lone)
    assert result[0]["args"].startswith("className=")
    assert result[0]["call"] == "click"
    assert result[-1]["call"] == "tap"


def test_matches_у_textContains_считается_подстрокой():
    target = node(0, text="Корзина (3)")
    other = node(1, text="Корзина пуста")
    result = build_selectors([target, other], target)
    contains = next(s for s in result if "textContains" in s["args"])
    assert contains["matches"] == 2


# ------------------------------------------------- цель размером с экран

def широкий(nid, desc, bounds):
    return Node(id=nid, parent=None, bounds=bounds, text="", resource_id="",
                description=desc, cls="android.view.View", clickable=False)


def test_цель_во_весь_экран_помечена_как_негодная():
    """Контейнер в 79% экрана уникален, но кнопкой не является.

    Найдено на живом WB: тап по тексту давал click(description="Ошибка!"),
    и рекордер рапортовал «✓ уникален». На прогоне такой клик бьёт в центр
    контейнера, а не туда, куда нажимал человек.
    """
    узел = широкий(0, "Ошибка!", (0.0, 0.1, 1.0, 0.9))
    кандидаты = build_selectors([узел], узел)
    по_описанию = [c for c in кандидаты if "description=" in c["args"]]
    assert по_описанию, "кандидат по описанию обязан остаться — как запасной"
    assert all(c["oversized"] for c in по_описанию), "должен быть помечен размером"


def test_обычная_кнопка_не_помечается():
    узел = широкий(0, "Купить", (0.1, 0.8, 0.9, 0.86))
    кандидаты = build_selectors([узел], узел)
    assert not any(c.get("oversized") for c in кандидаты)


def test_негодные_по_размеру_уходят_вниз_списка():
    узел = широкий(0, "Ошибка!", (0.0, 0.1, 1.0, 0.9))
    кандидаты = build_selectors([узел], узел)
    первый = кандидаты[0]
    assert first_ok(первый), f"наверху оказался негодный кандидат: {первый}"


def first_ok(c):
    return c["call"] == "tap" or not c.get("oversized")


def test_подпись_одолженная_у_мелкого_потомка_не_спасает_контейнер():
    """Случай с живого Wildberries.

    Контейнер в 79% экрана подписи не имеет; resolve_down берёт её у потомка
    в 1.6% («Ошибка!»). Селектор выглядит отличным — matches=1, не fragile, —
    но click по нему бьёт в центр потомка, мимо места тапа на 214 px.
    Решает размер ЦЕЛИ, а не источника подписи.
    """
    контейнер = Node(id=0, parent=None, bounds=(0.0, 0.06, 1.0, 0.85), text="",
                     resource_id="", description="", cls="android.view.View",
                     clickable=False)
    подпись = Node(id=1, parent=0, bounds=(0.42, 0.30, 0.58, 0.36), text="",
                   resource_id="", description="Ошибка!", cls="android.view.View",
                   clickable=False)
    контейнер.children.append(1)
    payload = to_payload([контейнер, подпись])

    кандидаты = payload[0]["selectors"]
    по_описанию = [c for c in кандидаты if "Ошибка!" in c["args"]]
    assert по_описанию, "кандидат остаётся — в инспекторе он может пригодиться"
    assert по_описанию[0]["oversized"], "но помечен: цель размером с экран"
    assert кандидаты[0]["call"] == "tap", "наверху должны быть координаты"
