"""Подбор селектора для узла и оценка его однозначности.

Кандидаты строятся под API сценариев: `ctx.click(**selector)` из
farm/context.py. Правила подъёма к предку описаны в docs/GOTCHAS.md.
"""
from __future__ import annotations

import re

from ..recorder import codegen
from .tree import Node

MAX_LIFT_LEVELS = 4
MAX_LIFT_AREA_RATIO = 4.0
ROOT_AREA = 0.95

# Доля экрана, выше которой узел перестаёт быть кнопкой. Найдено на живом
# приложении: тап по тексту попадал в контейнер на 79% экрана с
# content-desc="Ошибка!". Селектор уникален (matches=1) и потому выглядел
# надёжным, но клик по нему бьёт в центр контейнера, а не туда, куда нажимал
# человек. Уникальность и пригодность — разные вещи.
MAX_CLICK_AREA = 0.25

PRIORITY = ("resourceId", "description", "text")


def _labeled(node: Node) -> bool:
    return bool(node.resource_id or node.description or node.text)


def resolve_target(nodes: list[Node], node: Node):
    """Узел, по которому строить селектор, и число пройденных вверх уровней.

    Кликабельный предок возвращается и без подписи: подпись для него потом
    ищется у потомков (`resolve_down`), а тап по центру предка — это тап по
    самой кнопке, что точнее тапа по случайному дочернему View.
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
            return current, level
    return node, 0


def resolve_down(nodes: list[Node], node: Node) -> Node | None:
    """Подписанный потомок для узла без подписи.

    Compose-плитки устроены как кликабельный View-контейнер без атрибутов с
    текстом или иконкой внутри. Селектор по потомку у uiautomator2 тапает
    центр потомка — он лежит внутри контейнера, и Android отдаёт касание
    кликабельному родителю (см. docs/GOTCHAS.md про el.click()).

    Порядок обхода — в ширину: подпись верхнего уровня («Одежда») лучше
    вложенного бейджа («−50%»). Среди равных берётся узел с атрибутом
    поприоритетнее: resourceId > description > text.
    """
    queue = list(node.children)
    found: list[Node] = []
    while queue:
        child = nodes[queue.pop(0)]
        queue.extend(child.children)
        if _labeled(child):
            found.append(child)
    for key in PRIORITY:
        for child in found:
            if _attr(child, key):
                return child
    return None


def _attr(node: Node, key: str) -> str:
    if key == "resourceId":
        return node.resource_id
    if key == "description":
        return node.description
    return node.text


def _literal(value: str) -> str:
    # Тот же литерал, что вставляет кодоген: подпись из нескольких строк с
    # сырым переводом строки давала .py, который не компилируется.
    return codegen.literal(value)


# Хвост из цифр, скобок и пунктуации: «Корзина (3)» → «Корзина». Селектор по
# основе текста переживает смену счётчика, точный text= — нет.
_TAIL_RE = re.compile(r"[\s\d().,:;!«»%+·-]+$")


def text_stem(value: str) -> str:
    return _TAIL_RE.sub("", value)


# Подпись, которая на следующем прогоне почти наверняка будет другой: время,
# счётчик лайков, «5 мин назад», @ник. Селектор по ней уникален сегодня и
# мёртв завтра. Не выбрасываем (иногда ничего другого нет) — понижаем и
# помечаем `dynamic`, чтобы панель сказала об этом человеку.
_DYNAMIC_RES = (
    re.compile(r"\d{1,2}:\d{2}"),                                   # 12:45
    re.compile(r"^[@#]\w"),                                          # @ник, #тег
    re.compile(r"\d\s*(k|m|к|м|тыс|млн|млрд)\.?$", re.I),             # 15K, 1,2 тыс.
    re.compile(r"\b(назад|ago)\b", re.I),                            # 5 мин назад
    re.compile(r"^(вчера|сегодня|только что|yesterday|today|now)$", re.I),
    re.compile(r"^\d+\s*(с|сек|мин|ч|д|дн|нед|мес|г|s|m|h|d|w)\.?$", re.I),  # 2 ч
    re.compile(r"^\d{1,2}\s+[а-яa-z]{3,}\.?$", re.I),                 # 18 окт
)


def is_dynamic(value: str) -> bool:
    """Подпись меняется сама: время, дата, счётчик, ник. Чистая функция."""
    value = (value or "").strip()
    if not value:
        return False
    if any(r.search(value) for r in _DYNAMIC_RES):
        return True
    digits = sum(c.isdigit() for c in value)
    if not digits:
        return False
    # Почти одни цифры («125», «+7 912…») или счётчик хвостом («Корзина (3)»).
    letters = sum(c.isalpha() for c in value)
    return letters < 2 or text_stem(value) != value


def _single(nodes: list[Node], node: Node) -> list[dict]:
    out = []
    for key in PRIORITY:
        value = _attr(node, key)
        if not value:
            continue
        out.append({
            "call": "click",
            "args": f"{key}={_literal(value)}",
            "matches": sum(1 for n in nodes if _attr(n, key) == value),
            "fragile": False,
            "dynamic": key != "resourceId" and is_dynamic(value),
        })
    stem = text_stem(node.text)
    if len(stem) >= 2 and stem != node.text:
        out.append({
            "call": "click",
            "args": f"textContains={_literal(stem)}",
            "matches": sum(1 for n in nodes if stem in n.text),
            "fragile": False,
            "dynamic": is_dynamic(stem),
        })
    return out


def _nth(nodes: list[Node], node: Node) -> list[dict]:
    """«Нужен вот этот»: номер среди узлов с тем же устойчивым признаком.

    Лайки в ленте: id и подпись у всех одинаковые, `d(resourceId=…)` нажмёт
    первый. `instance` в uiautomator2 — номер среди совпавших в порядке
    обхода дерева, тот же порядок, что у дампа. Хрупко (лента сдвинется —
    номер укажет на другой пост), но точнее className+instance, где номер
    считается среди всех ImageView экрана.
    """
    out = []
    for key in PRIORITY:
        value = _attr(node, key)
        if not value or (key != "resourceId" and is_dynamic(value)):
            continue
        same = [n.id for n in nodes if _attr(n, key) == value]
        if len(same) < 2 or node.id not in same:
            continue
        k = same.index(node.id)
        out.append({
            "call": "click",
            "args": f"{key}={_literal(value)}, instance={k}",
            "matches": 1,
            "fragile": True,
            "dynamic": False,
            "nth": [k + 1, len(same)],
        })
    return out


def _combined(nodes: list[Node], node: Node) -> list[dict]:
    out = _nth(nodes, node)
    for key in PRIORITY:
        value = _attr(node, key)
        if not value:
            continue
        matches = sum(1 for n in nodes if _attr(n, key) == value and n.cls == node.cls)
        # Тип элемента тот же у всех похожих — сочетание ничего не сужает и
        # только загромождает список выбора.
        if matches != 1:
            continue
        out.append({
            "call": "click",
            "args": f"{key}={_literal(value)}, className={_literal(node.cls)}",
            "matches": matches,
            "fragile": True,
            "dynamic": key != "resourceId" and is_dynamic(value),
        })
    out.append(_instance(nodes, node))
    return out


def _instance(nodes: list[Node], node: Node) -> dict:
    same_class = [n.id for n in nodes if n.cls == node.cls]
    return {
        "call": "click",
        "args": f"className={_literal(node.cls)}, instance={same_class.index(node.id)}",
        "matches": 1,
        "fragile": True,
        "dynamic": False,
    }


def _by_coordinates(node: Node) -> list[dict]:
    cx = round((node.bounds[0] + node.bounds[2]) / 2, 3)
    cy = round((node.bounds[1] + node.bounds[3]) / 2, 3)
    return [{"call": "tap", "args": f"{cx}, {cy}", "matches": 1, "fragile": True,
             "dynamic": False}]


def _mark_oversized(candidates: list[dict], node: Node) -> list[dict]:
    """Пометить кандидатов, чья цель размером с пол-экрана.

    Проверять надо размер ЦЕЛИ, а не того узла, у которого одолжили подпись.
    На живом приложении контейнер в 79% экрана подписи не имел, и
    resolve_down взял её у потомка в 1.6% («Ошибка!»). Селектор выглядел
    отличным — matches=1, не fragile, — но click по нему бил в центр этого
    потомка: мимо места тапа на 214 px.

    Не выбрасываем: иногда это единственное, что есть, и в инспекторе человек
    решит сам. Но наверх списка такой кандидат подниматься не должен, а
    рекордер по нему не пишет click вслепую. Координатный кандидат бьёт ровно
    в центр узла и от размера цели не страдает — его не помечаем.
    """
    oversized = node.area > MAX_CLICK_AREA
    for c in candidates:
        c["oversized"] = bool(oversized and c["call"] != "tap")
    # Пометить мало — надо и переранжировать: to_payload зовёт эту функцию уже
    # после сортировки внутри build_selectors, и без повторного порядка
    # негодный кандидат остался бы наверху.
    # Порядок: годный размер → один такой на экране → подпись не меняется
    # сама → не хрупкий. Внутри равных — как построены: resourceId раньше
    # подписи, номер по id раньше номера по типу, координаты последними.
    candidates.sort(key=lambda c: (c["oversized"], c["matches"] != 1,
                                   c.get("dynamic", False), c["fragile"],
                                   c["call"] == "tap"))
    return candidates


def build_selectors(nodes: list[Node], node: Node) -> list[dict]:
    """Кандидаты от самого надёжного к самому хрупкому.

    `matches` — сколько узлов дампа удовлетворяют селектору при точном
    сравнении строк, как это делает uiautomator2.
    """
    out = _single(nodes, node)
    # Уникальная, но меняющаяся подпись («125») — не повод не предложить
    # устойчивый номер среди одинаковых.
    if out and not any(s["matches"] == 1 and not s["dynamic"] for s in out):
        out += _combined(nodes, node) if node.cls else _nth(nodes, node)
    if not out:
        # Узел без единой подписи: className+instance хрупок (порядок узлов
        # на другом экране другой), но всё же селектор, а не слепой тап.
        out = [_instance(nodes, node)] if node.cls else []
        return _mark_oversized(out + _by_coordinates(node), node)
    # Цель размером с экран всегда идёт ниже годных: она уникальна, но клик по
    # ней бьёт в центр контейнера, а не туда, куда нажимал человек.
    return _mark_oversized(out + _by_coordinates(node), node)


def to_payload(nodes: list[Node]) -> list[dict]:
    """Узлы в JSON-виде для фронта, с готовыми селекторами."""
    out = []
    for node in nodes:
        target, lift = resolve_target(nodes, node)
        sel_node = target
        if not _labeled(target):
            sel_node = resolve_down(nodes, target) or target
        out.append({
            "id": node.id,
            "parent": node.parent,
            "bounds": list(node.bounds),
            "text": node.text,
            "resourceId": node.resource_id,
            "description": node.description,
            "class": node.cls,
            "clickable": node.clickable,
            "textDynamic": is_dynamic(node.text),
            "descriptionDynamic": is_dynamic(node.description),
            "target": target.id,
            "lift": lift,
            "selectors": _mark_oversized(build_selectors(nodes, sel_node), target),
        })
    return out
