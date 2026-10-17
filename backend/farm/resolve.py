"""Многослойный резолвер цели: селекторы → текст → OCR → шаблон → координаты.

Здесь чистое сопоставление и порядок слоёв. Экран резолвер видит только через
ctx, поэтому проверяется на фейке, без устройства.
"""
from __future__ import annotations

import difflib
import time
from dataclasses import dataclass

from .ui import tree
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

    def __post_init__(self) -> None:
        # geometry.to_pixels() считает долями только строго 0..1: OCR
        # ("1 - (y + h/2)" на рамке у края экрана) и at= сценария не
        # проходят через клэмп ui/tree.py и промах на 0.004 даёт не ошибку,
        # а тап в (0,0) — «Назад»/«Закрыть» на большинстве экранов. Клэмп
        # здесь, в одной точке, покрывает все слои разом.
        object.__setattr__(self, "x", min(max(self.x, 0.0), 1.0))
        object.__setattr__(self, "y", min(max(self.y, 0.0), 1.0))


def resolve(ctx, sel=None, text=None, img=None, at=None, timeout: float = 10.0):
    """Первый сработавший слой.

    Дерево (селекторы и текст) крутится до таймаута — экран может дорисоваться.
    Зрение пробуется по разу: оно дорогое, а повторный снимок того же экрана
    ничего не добавит.
    """
    sel = list(sel or ())
    text = list(text or ())
    if not (sel or text or img or at):
        raise ValueError("пустая цель: нужен хотя бы один слой")

    deadline = time.time() + timeout
    while sel or text:   # без этих слоёв круг только жёг бы процессор
        ctx.check_cancel()
        for s in sel:
            el = ctx.find(timeout=1.0, **s)
            if el is not None:
                center = _center(el, ctx.size)
                if center:
                    return Hit(center[0], center[1], "selector", str(s))
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
        # Без цели вида sel единственный ограничитель темпа — сама
        # длительность dump_hierarchy: 10-30 полных дампов за провалившийся
        # шаг на каждом из 20 устройств. Пауза капается остатком до
        # дедлайна, чтобы короткие timeout в тестах не начали идти дольше.
        time.sleep(min(0.3, max(0.0, deadline - time.time())))

    if text and ocr_mod.backend():
        hit = _by_ocr(ctx, text)
        if hit:
            return hit
    if img:
        hit = _by_template(ctx, img)
        if hit:
            return hit
    if at:
        return Hit(float(at[0]), float(at[1]), "point")
    return None


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
    items = []
    for node in nodes:
        label = (node.text or node.description or "").strip()
        if label:
            items.append((label,
                          (node.bounds[0] + node.bounds[2]) / 2,
                          (node.bounds[1] + node.bounds[3]) / 2))
    found = match_text(items, wanted)
    return Hit(found[1], found[2], "tree-text", found[0]) if found else None


def _by_ocr(ctx, wanted):
    try:
        boxes = ocr_mod.ocr(ctx.screen_bytes())
    except Exception:  # noqa: BLE001 — OCR не должен ронять шаг
        return None
    found = match_text([(b.text, b.cx, b.cy) for b in boxes], wanted)
    return Hit(found[1], found[2], "ocr", found[0]) if found else None


def _by_template(ctx, img):
    if not tpl_mod.available():
        return None
    try:
        data, base_scale = ctx.asset(img)
        if not data:
            return None
        found = tpl_mod.find(ctx.screen_bytes(), data, base_scale=base_scale)
    except Exception:  # noqa: BLE001 — зрение не должно ронять шаг, как _by_ocr/_by_tree_text
        return None
    if found:
        return Hit(found[0], found[1], "template", f"{img} score={found[2]:.2f}")
    return None
