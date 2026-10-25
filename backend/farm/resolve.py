"""Многослойный резолвер цели: селекторы → текст → OCR → шаблон → координаты.

Здесь чистое сопоставление и порядок слоёв. Экран резолвер видит только через
ctx, поэтому проверяется на фейке, без устройства.
"""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass

from . import config
from .ui import scope, tree
from .vision import ocr as ocr_mod
from .vision import synonyms
from .vision import template as tpl_mod
from .vision.synonyms import normalize as _norm

# OCR путает кириллицу с визуально неотличимой латиницей: «Вoйти» с латинской
# «o» перестаёт совпадать с «Войти». Приводим обе стороны к одному алфавиту ДО
# сравнения (см. synonyms.normalize и общую таблицу synonyms.HOMOGLYPHS).
# Понизить вместо этого порог нечёткости нельзя: difflib даёт «войти»/«вoйти»
# (шум) и «войти»/«выйти» (ВХОД против ВЫХОДА) одинаковые 0.8 — порогом эти
# случаи не разделяются, а ценой ошибки будет выход из аккаунта. В таблице
# гомоглифов только по-настоящему неотличимые пары; «b/в», «h/н» и прочие
# похожие-но-различимые туда не входят.
FUZZY_RATIO = 0.85
LOOP_PAUSE = 0.3   # пауза между кругами поиска по дереву


def match_text(items, wanted):
    """Первый подходящий (текст, cx, cy): точное → вхождение → нечёткое."""
    variants = set()
    for w in wanted:
        variants |= synonyms.expand(w)
    # synonyms.expand() отдаёт варианты как обычные слова языка (без перевода
    # гомоглифов), поэтому нормализуем их здесь же — иначе латинская "allow"
    # не совпадёт с уже нормализованным (кириллизованным) текстом экрана.
    variants = {_norm(v) for v in variants}
    normed = [(_norm(t), (t, x, y)) for t, x, y in items if _norm(t)]
    for norm, item in normed:
        if norm in variants:
            return item

    # Вхождение: варианты короче 4 символов («ok», «да», «нет») исключаем —
    # для них вхождение в длинную фразу почти всегда ложное (например,
    # "ok" — подстрока normalize("cookie policy") через гомоглиф o→о).
    # Среди оставшихся кандидатов берём кратчайший узел, а не первый по
    # порядку дерева: длинная фраза, содержащая нужное слово мимоходом
    # (ссылка на политику cookies), не должна перебивать саму кнопку.
    entry = None
    for norm, item in normed:
        if entry is not None and len(norm) >= len(entry[0]):
            continue
        if any(len(v) >= 4 and v in norm for v in variants):
            entry = (norm, item)
    if entry:
        return entry[1]

    best = None
    for norm, item in normed:
        for v in variants:
            ratio = difflib.SequenceMatcher(None, v, norm).ratio()
            if ratio >= FUZZY_RATIO and (best is None or ratio > best[0]):
                best = (ratio, item)
    return best[1] if best else None


@dataclass(frozen=True)
class Hit:
    x: float
    y: float
    layer: str
    detail: str = ""
    # Узел — переключатель/галочка: проверка «нажатие подействовало» для него
    # повторять тап не должна (второй тап вернул бы переключатель назад).
    checkable: bool = False

    def __post_init__(self) -> None:
        # geometry.to_pixels() считает долями только строго 0..1: OCR
        # ("1 - (y + h/2)" на рамке у края экрана) и at= сценария не
        # проходят через клэмп ui/tree.py и промах на 0.004 даёт не ошибку,
        # а тап в (0,0) — «Назад»/«Закрыть» на большинстве экранов. Клэмп
        # здесь, в одной точке, покрывает все слои разом.
        object.__setattr__(self, "x", min(max(self.x, 0.0), 1.0))
        object.__setattr__(self, "y", min(max(self.y, 0.0), 1.0))


def resolve(ctx, sel=None, text=None, img=None, at=None, timeout: float = 10.0,
            within=None, near=None, at_rel=None, blind: bool = True, why=None):
    """Первый сработавший слой.

    Дерево (селекторы и текст) крутится до таймаута — экран может дорисоваться.
    Зрение пробуется по разу: оно дорогое, а повторный снимок того же экрана
    ничего не добавит.

    within/near — место поиска (farm/ui/scope.py), его соблюдает каждый слой:
    см. `_resolve_scoped`. `blind=False` — без слоя точки (листание к цели:
    после свайпа сохранённое место на экране ничего не значит). `why` — список,
    куда пишется причина промаха с местом: "within", "near" или "target".
    """
    sel = list(sel or ())
    text = list(text or ())
    if within or near:
        if not (sel or text or img or at_rel):
            raise ValueError("пустая цель: нужен хотя бы один слой")
        return _resolve_scoped(ctx, sel, text, img, at_rel, timeout, within, near,
                               blind, why)
    if not (sel or text or img or at):
        raise ValueError("пустая цель: нужен хотя бы один слой")

    # Память нейросети: селекторы, которые она уже подобрала для ЭТОЙ цели на
    # другом телефоне. Добавляются в конец: свои селекторы сценария главнее.
    vlm_key, learned = _vlm_learned(ctx, sel, text, img, at)
    orig_sel = list(sel)
    sel = sel + [s for s in learned if s not in sel]

    deadline = time.time() + timeout
    while sel or text:   # без этих слоёв круг только жёг бы процессор
        ctx.check_cancel()
        for s in sel:
            el = ctx.find(timeout=1.0, **s)
            if el is not None:
                center = _center(el, ctx.size)
                if center:
                    if s not in orig_sel:
                        _say(ctx, "цель найдена селектором из памяти нейросети — без вызова")
                    if s not in orig_sel and _learned_denied(ctx, el):
                        continue   # выученный селектор не обходит запрет необратимого
                    node, nodes = _node_of_el(ctx, el) if config.TAPCOVER else (None, [])
                    if node is not None:
                        center = free_point(nodes, node)
                    return Hit(center[0], center[1], "selector", str(s),
                               checkable=_el_checkable(el))
        if text:
            hit = _by_tree_text(ctx, text)
            if hit:
                return hit
        if time.time() >= deadline:
            break
        # Темп круга ничем больше не ограничен: цель без селекторов упирается
        # только в длительность самого dump_hierarchy, а это десятки полных
        # дампов за один провалившийся шаг — и так на каждом из двадцати
        # устройств. Спим не дольше, чем осталось до таймаута, иначе короткие
        # ожидания растягивались бы до длины паузы.
        time.sleep(min(LOOP_PAUSE, max(0.0, deadline - time.time())))

    if text and ocr_mod.backend():
        hit = _by_ocr(ctx, text)
        if hit:
            return hit
    if img:
        hit = _by_template(ctx, img, at)
        if hit:
            return hit
    # Шестой слой — нейросеть. Стоит ПЕРЕД точкой: точка слепа (помнит место, но
    # не видит экран, и перед ней приходится спрашивать человека), а нейросеть
    # смотрит на кадр. Выключена по умолчанию; без blind (листание) и с местом
    # поиска не зовётся: там каждый круг был бы платным вызовом.
    if blind and (sel or text):
        hit = _by_vlm(ctx, orig_sel, text, vlm_key)
        if hit:
            return hit
    if at and blind:
        return Hit(float(at[0]), float(at[1]), "point")
    return None


def _say(ctx, msg):
    try:
        ctx.log(msg)
    except Exception:  # noqa: BLE001
        pass


def _vlm_learned(ctx, sel, text, img, at):
    try:
        from .vlm import learn
        k = learn.key(ctx, sel, text, img, at)
        return k, learn.lookup(k)
    except Exception:  # noqa: BLE001 — память нейросети не должна ломать поиск
        return "", []


def _learned_denied(ctx, el) -> bool:
    """Узел, найденный выученным селектором, оказался необратимым действием?
    Тогда это промах слоя + отклонение vlm_denied. Не смогли прочесть узел —
    тоже отказ: осторожность по умолчанию."""
    try:
        from .vlm import locate as vlm_locate, safety
        info = el.info if hasattr(el, "info") else {}
        texts = [info.get("text"), info.get("contentDescription")]
        bad = safety.irreversible(*[t for t in texts if t])
        if bad:
            vlm_locate._refuse(ctx, [t for t in texts if t], bad, "выученный селектор")
        return bool(bad)
    except Exception:  # noqa: BLE001
        return True


def _by_vlm(ctx, sel, text, key):
    try:
        from .vlm import locate as vlm_locate
        what = {"text": text, "sel": sel, "key": key,
                "label": getattr(ctx, "step_label", "")}
        return vlm_locate.locate(ctx, what)
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------ место поиска у запасных слоёв

def _box_center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def place_of(nodes, within=None, near=None):
    """Где искать по этому дампу: ("within", рамка контейнера, узел) или
    ("near", центр ориентира, узел); None — их на экране нет. Тот же первый
    совпавший узел, что берёт scope.pick."""
    if within:
        found = scope.find(nodes, dict(within))
        return ("within", tuple(found[0].bounds), found[0]) if found else None
    sel, direction = scope.split_near(near)
    found = scope.find(nodes, dict(sel))
    return (("near", _box_center(found[0].bounds), found[0], direction)
            if found else None)


def point_from(place, rel):
    """Точка шага от места: внутри — доли рамки контейнера, рядом с —
    смещение от центра ориентира в долях экрана. Чистая функция."""
    kind, where = place[0], place[1]
    if kind == "within":
        x1, y1, x2, y2 = where
        return (x1 + float(rel[0]) * (x2 - x1), y1 + float(rel[1]) * (y2 - y1))
    return (where[0] + float(rel[0]), where[1] + float(rel[1]))


def _in_box(x, y, b) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def _nearest(items, point):
    """(текст, x, y), ближайший к точке."""
    return min(items, key=lambda it: (it[1] - point[0]) ** 2 + (it[2] - point[1]) ** 2)


def match_tier(items, wanted):
    """Все (текст, x, y) лучшей ступени совпадения match_text: точные, иначе
    вхождения, иначе нечёткие. Нужна, чтобы среди равных выбрать по месту."""
    variants = set()
    for w in wanted:
        variants |= synonyms.expand(w)
    variants = {_norm(v) for v in variants}
    normed = [(_norm(t), (t, x, y)) for t, x, y in items if _norm(t)]
    exact = [item for norm, item in normed if norm in variants]
    if exact:
        return exact
    entry = [item for norm, item in normed if any(len(v) >= 4 and v in norm for v in variants)]
    if entry:
        return entry
    return [item for norm, item in normed
            if any(difflib.SequenceMatcher(None, v, norm).ratio() >= FUZZY_RATIO
                   for v in variants)]


def _tree_text_scoped(nodes, wanted, place):
    """Слой текста по дереву с местом: только внутри контейнера / из всех
    подходящих надписей — ближайшая к ориентиру (как scope.closest)."""
    kind, box = place[0], place[2]
    direction = place[3] if len(place) > 3 else ""
    if kind == "within":
        pool = [n for n in nodes if scope.inside(nodes, n, box)]
    else:
        pool = [n for n in nodes if n.id != box.id]
    items, by_item = [], {}
    for node in pool:
        label = (node.text or node.description or "").strip()
        if label:
            c = _box_center(node.bounds)
            item = (label, c[0], c[1], node.id)
            items.append(item)
    tier = match_tier([it[:3] for it in items], wanted)
    if not tier:
        return None
    # match_tier отдаёт тройки; узел нужен для близости по дереву
    for it in items:
        by_item.setdefault(it[:3], nodes[it[3]])
    if kind == "near":
        ranked = scope.closest(nodes, [by_item[it] for it in tier], box, direction)
        if not ranked:
            return None      # подходящие надписи есть, но не с той стороны
        node = ranked[0]
        c = free_point(nodes, node)
        return Hit(c[0], c[1], "tree-text", (node.text or node.description).strip(),
                   checkable=node.checkable)
    found = match_text(tier, wanted)
    return Hit(found[1], found[2], "tree-text", found[0])


def _resolve_scoped(ctx, sel, text, img, at_rel, timeout, within, near, blind, why):
    """Все слои с местом поиска. Нет контейнера/ориентира — промах всех слоёв,
    и точка тоже не нажимается: тап «туда, где было» без места — это не
    «рядом с», а любой пост ленты. Абсолютная точка шага здесь не берётся
    вовсе — только смещение от места (`at_rel`)."""
    deadline = time.time() + timeout
    place = None
    while True:
        ctx.check_cancel()
        try:
            w, h = ctx.size
            nodes = tree.parse(ctx.dump_hierarchy(), w, h)
        except Exception:  # noqa: BLE001 — дамп не снялся, следующий круг
            nodes = []
        try:
            place = place_of(nodes, within, near) if nodes else None
            if place is not None:
                for s in sel:
                    node, _ = scope.pick(nodes, dict(s), within, near)
                    if node is not None:
                        c = free_point(nodes, node)
                        return Hit(c[0], c[1], "selector", str(s),
                                   checkable=node.checkable)
                if text:
                    hit = _tree_text_scoped(nodes, text, place)
                    if hit:
                        return hit
        except scope.ScopeError as e:
            ctx.fail(str(e))
        if time.time() >= deadline:
            break
        time.sleep(min(LOOP_PAUSE, max(0.0, deadline - time.time())))
    if place is None:
        if why is not None:
            why.append("within" if within else "near")
        return None
    if why is not None:
        why.append("target")
    kind, where = place[0], place[1]
    # Ожидаемое место цели: от места со смещением шага; у «рядом с» без
    # смещения — сам ориентир. Зрение дерева не знает, поэтому «ближе» здесь —
    # по экрану; смещение и решает, чей это лайк — этого поста или соседнего.
    expect = point_from(place, at_rel) if at_rel else None
    if text and ocr_mod.backend():
        hit = (_by_ocr(ctx, text, box=where, point=expect) if kind == "within"
               else _by_ocr(ctx, text, point=expect or where))
        if hit:
            return hit
    if img:
        if kind == "within":
            hit = _by_template(ctx, img, expect, region=where)
        else:
            hit = _by_template(ctx, img, expect or where)
        if hit:
            return hit
    if at_rel and blind:
        x, y = point_from(place, at_rel)
        return Hit(x, y, "point", "от места поиска")
    return None


def free_point(nodes, node):
    """Центр узла или, если его перекрыл кликабельный брат, свободная точка рамки.

    Перекрытие доказывается только порядком детей одного родителя
    (tree.coverers); иначе это ровно центр, как раньше."""
    try:
        point = tree.tap_point(node, tree.coverers(nodes, node))
    except Exception:  # noqa: BLE001 — геометрия не должна ронять поиск цели
        point = None
    return point or _box_center(node.bounds)


def _node_of_el(ctx, el):
    """Узел дампа, соответствующий элементу uiautomator2 (по рамке), и все
    узлы; (None, []) — не нашли или дамп не снялся."""
    try:
        w, h = ctx.size
        b = el.info["bounds"]
        nodes = tree.parse(ctx.dump_hierarchy(), w, h)
        want = (b["left"] / w, b["top"] / h, b["right"] / w, b["bottom"] / h)
        for n in nodes:
            if all(abs(n.bounds[i] - want[i]) < 1.5 / max(w, h) for i in range(4)):
                return n, nodes
    except Exception:  # noqa: BLE001 — перекрытие необязательно, тап пойдёт в центр
        pass
    return None, []


def _el_checkable(el) -> bool:
    try:
        return bool(el.info.get("checkable"))
    except Exception:  # noqa: BLE001
        return False


def _center(el, size):
    try:
        b = el.info["bounds"]
        w, h = size
        return ((b["left"] + b["right"]) / 2 / w, (b["top"] + b["bottom"]) / 2 / h)
    except Exception:  # noqa: BLE001 — элемент испарился, слой считается промахом
        return None


def _by_tree_text(ctx, wanted):
    try:
        w, h = ctx.size
        nodes = tree.parse(ctx.dump_hierarchy(), w, h)
    except Exception:  # noqa: BLE001 — дамп не снялся
        return None
    items, owners = [], {}
    for node in nodes:
        label = (node.text or node.description or "").strip()
        if label:
            item = (label,
                    (node.bounds[0] + node.bounds[2]) / 2,
                    (node.bounds[1] + node.bounds[3]) / 2)
            items.append(item)
            owners.setdefault(item, node)
    found = match_text(items, wanted)
    if not found:
        return None
    node = owners.get(found)
    if node is not None and config.TAPCOVER:
        x, y = free_point(nodes, node)
        return Hit(x, y, "tree-text", found[0], checkable=node.checkable)
    return Hit(found[1], found[2], "tree-text", found[0])


def screen_secure(ctx) -> bool:
    """Экран защищён от снимков (FLAG_SECURE): кадр чёрный, OCR и шаблону
    нечего искать. Контексты-заглушки без serial считаются обычными."""
    serial = getattr(ctx, "serial", None)
    if not isinstance(serial, str):
        return False
    from .control import capture
    return capture.is_secure(serial)


def _by_ocr(ctx, wanted, box=None, point=None):
    if screen_secure(ctx):
        return None
    try:
        boxes = ocr_mod.ocr(ctx.screen_bytes())
    except Exception:  # noqa: BLE001 — OCR не должен ронять шаг
        return None
    items = [(b.text, b.cx, b.cy) for b in boxes]
    if box is not None or point is not None:
        # Место поиска: только надписи в рамке контейнера; среди равных —
        # ближайшая к ожидаемой точке (ориентир со смещением шага).
        if box is not None:
            items = [it for it in items if _in_box(it[1], it[2], box)]
        tier = match_tier(items, wanted)
        if not tier:
            return None
        found = _nearest(tier, point) if point is not None else match_text(tier, wanted)
        return Hit(found[1], found[2], "ocr", found[0])
    found = match_text(items, wanted)
    return Hit(found[1], found[2], "ocr", found[0]) if found else None


def _by_template(ctx, img, at=None, region=None):
    if not tpl_mod.available() or screen_secure(ctx):
        return None
    try:
        data, base_scale = ctx.asset(img)
        if not data:
            return None
        # Место записи решает, какую из одинаковых иконок нажать; рамка
        # контейнера («внутри») — где их вообще искать.
        extra = {"region": tuple(region)} if region else {}
        if at:
            found = tpl_mod.find(ctx.screen_bytes(), data, base_scale=base_scale,
                                 near=(float(at[0]), float(at[1])), with_count=True, **extra)
        else:
            found = tpl_mod.find(ctx.screen_bytes(), data, base_scale=base_scale, **extra)
    except Exception:  # noqa: BLE001 — зрение не должно ронять шаг, как _by_ocr/_by_tree_text
        return None
    if found:
        detail = f"{img} score={found[2]:.2f}"
        if len(found) > 3 and found[3] > 1:
            detail += f", похожих: {found[3]} — взято ближайшее к месту записи" if at \
                else f", похожих: {found[3]}"
        return Hit(found[0], found[1], "template", detail)
    return None
