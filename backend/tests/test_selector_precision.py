"""Точность выбора цели: меняющийся текст, одинаковые кнопки в ленте, картинка.

Владелец: «по тексту нельзя, если текст — счётчик или время»; «у лайков в
ленте один и тот же id — нужен вот этот»; «если картинок несколько — какая?».
"""
import re

import pytest

from farm import resolve
from farm.context import normalize_target
from farm.recorder import codegen, steps
from farm.ui import selectors, tree
from farm.ui.selectors import build_selectors, is_dynamic, to_payload
from farm.ui.tree import Node
from farm.vision import template


# ------------------------------------------------ меняющийся текст

@pytest.mark.parametrize("value", [
    "12:45", "125", "1,2 тыс.", "15K", "3.4M", "@ivan_petrov", "5 мин назад",
    "2 ч", "вчера", "Сегодня", "Корзина (3)", "18 окт", "+7 912 345-67-89",
])
def test_меняющийся_текст_распознаётся(value):
    assert is_dynamic(value), value


@pytest.mark.parametrize("value", [
    "Войти", "Нравится", "Корзина", "Подписаться", "Wi-Fi", "Ещё", "OK", "",
])
def test_обычная_подпись_не_считается_меняющейся(value):
    assert not is_dynamic(value), value


def btn(nid, text="", rid="", desc="", bounds=(0.1, 0.1, 0.3, 0.2),
        cls="android.widget.ImageView"):
    return Node(id=nid, parent=None, bounds=bounds, text=text, resource_id=rid,
                description=desc, cls=cls, clickable=True)


def test_уникальный_счётчик_уступает_устойчивому_признаку():
    """Подпись «125» уникальна, но после лайка станет «126» — шаг не найдёт."""
    target = btn(0, text="125", desc="Комментарии")
    twin = btn(1, desc="Комментарии", bounds=(0.1, 0.5, 0.3, 0.6))
    result = build_selectors([target, twin], target)
    by_text = next(c for c in result if c["args"] == 'text="125"')
    assert by_text["dynamic"] is True and by_text["matches"] == 1
    assert result[0]["args"] == 'description="Комментарии", instance=0'
    assert result[0]["dynamic"] is False


def test_основа_текста_со_счётчиком_не_меняется():
    target = btn(0, text="Корзина (3)")
    result = build_selectors([target], target)
    stem = next(c for c in result if c["args"] == 'textContains="Корзина"')
    exact = next(c for c in result if c["args"] == 'text="Корзина (3)"')
    assert stem["dynamic"] is False and exact["dynamic"] is True
    assert result[0]["args"] == 'textContains="Корзина"'


def test_только_время_остаётся_в_списке_но_не_первым():
    target = btn(0, text="12:45", cls="android.widget.TextView")
    result = build_selectors([target], target)
    by_text = next(c for c in result if c["args"] == 'text="12:45"')
    assert by_text["dynamic"] is True, "остаётся в списке, но помечен"
    # наверху — то, что не зависит от показаний часов
    assert result[0]["dynamic"] is False and result[0]["call"] == "click"


def test_payload_говорит_какие_подписи_меняются():
    node = btn(0, text="5 мин назад", desc="Профиль")
    p = to_payload([node])[0]
    assert p["textDynamic"] is True and p["descriptionDynamic"] is False


# ------------------------------------------------ одинаковые кнопки в ленте

def лента():
    """Три поста, у каждого лайк с одним id и подписью и свой счётчик."""
    nodes = []
    for i in range(3):
        y = 0.1 + i * 0.3
        nodes.append(btn(len(nodes), rid="app:id/like", desc="Нравится",
                         bounds=(0.05, y, 0.15, y + 0.05)))
        nodes.append(Node(id=len(nodes), parent=None, bounds=(0.16, y, 0.3, y + 0.05),
                          text=str(10 + i), resource_id="app:id/count", description="",
                          cls="android.widget.TextView", clickable=False))
    return nodes


def test_одинаковые_лайки_нужен_вот_этот_по_номеру():
    nodes = лента()
    result = build_selectors(nodes, nodes[2])   # второй лайк
    first = result[0]
    assert first["args"] == 'resourceId="app:id/like", instance=1'
    assert first["matches"] == 1
    assert first["nth"] == [2, 3]
    # общий селектор остаётся в списке и честно говорит, сколько таких
    common = next(c for c in result if c["args"] == 'resourceId="app:id/like"')
    assert common["matches"] == 3


def test_номер_по_id_лучше_номера_по_типу_элемента():
    nodes = лента()
    args = [c["args"] for c in build_selectors(nodes, nodes[4])]
    assert args.index('resourceId="app:id/like", instance=2') < next(
        i for i, a in enumerate(args) if a.startswith("className="))


def test_бесполезные_сочетания_с_типом_не_предлагаются():
    """className тот же у всех трёх лайков — сочетание не сужает выбор."""
    nodes = лента()
    for c in build_selectors(nodes, nodes[0]):
        if "className=" in c["args"] and "instance=" not in c["args"]:
            assert c["matches"] == 1, c


def test_номер_среди_похожих_проходит_сохранение_и_прогон():
    """«Нужен вот этот» + «или так» доходят до ctx.click_any/click_target."""
    nodes = лента()
    main = build_selectors(nodes, nodes[2])[0]["args"]
    step = steps.normalize_step({
        "kind": "click", "args": {},
        "selector": {"call": "click", "args": main,
                     "fallbacks": ['description="Нравится"']}})
    src = codegen.render({"name": "t", "description": "", "watch_popups": False}, {}, [step])
    assert 'ctx.click_any(dict(resourceId="app:id/like", instance=1), dict(description="Нравится"))' in src
    chain = [eval("dict(" + a + ")", {"dict": dict})
             for a in [main, 'description="Нравится"']]
    assert normalize_target({"sel": chain})["sel"] == chain


def test_из_xml_номер_совпадает_с_порядком_дампа():
    xml = ('<hierarchy><node class="F" bounds="[0,0][1080,2400]">'
           + "".join(f'<node class="I" resource-id="a:id/like" clickable="true" '
                     f'bounds="[0,{i * 300}][100,{i * 300 + 100}]"/>' for i in range(3))
           + '</node></hierarchy>')
    nodes = tree.parse(xml, 1080, 2400)
    payload = to_payload(nodes)
    assert payload[3]["selectors"][0]["args"] == 'resourceId="a:id/like", instance=2'


# ------------------------------------------------ картинка: несколько совпадений

def test_из_нескольких_совпадений_картинки_берётся_ближайшее_к_месту_записи():
    peaks = [(0.2, 0.2, 0.97), (0.2, 0.5, 0.95), (0.2, 0.8, 0.96)]
    assert template.pick(peaks, near=(0.2, 0.55))[:2] == (0.2, 0.5)
    assert template.pick(peaks, near=None)[:2] == (0.2, 0.2)
    assert template.pick([], near=(0.5, 0.5)) is None


def test_соседние_пики_одного_места_схлопываются():
    raw = [(0.50, 0.50, 0.95), (0.501, 0.502, 0.94), (0.5, 0.9, 0.9)]
    kept = template.suppress(raw, min_dx=0.02, min_dy=0.02)
    assert [p[:2] for p in kept] == [(0.50, 0.50), (0.5, 0.9)]


def test_резолвер_передаёт_место_записи_в_поиск_картинки(monkeypatch):
    seen = {}

    def fake_find(s, t, base_scale=1.0, near=None, with_count=False):
        seen["near"] = near
        assert with_count
        return (0.2, 0.5, 0.9, 3)

    monkeypatch.setattr(template, "available", lambda: True)
    monkeypatch.setattr(template, "find", fake_find)

    class Ctx:
        size = (1080, 2400)

        def check_cancel(self):
            pass

        def asset(self, name):
            return b"png", 1.0

        def screen_bytes(self):
            return b"png"

    hit = resolve.resolve(Ctx(), img="a.png", at=(0.2, 0.55), timeout=0.1)
    assert seen["near"] == (0.2, 0.55)
    assert hit.layer == "template" and "похожих: 3" in hit.detail
