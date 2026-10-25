"""Отпечаток экрана и счёт похожести двух экранов.

Точное совпадение «этот экран — тот же» на живом приложении почти не
встречается: сменился счётчик, подгрузилась одна карточка — и строгое
сравнение говорит «другой». Поэтому экран сводится к множеству ключей узлов
(без рамок: они плывут от разрешения и прокрутки), а похожесть — это доля
общих ключей (Жаккар) плюс совпадение пакета. Так «почти тот же экран» и
«совсем другой» получают разные числа, и человеку можно написать «похож на
эталон на 92%» вместо голого «не нашёл».

Узлы шторки и статус-бара (часы, батарея — чужой пакет) в отпечаток не входят:
иначе минута на часах делала бы каждый экран «новым». Модуль не знает про adb.
"""
from __future__ import annotations

from .ui import tree

# Вес множества ключей и пакета в итоговом счёте. Пакет — отдельная доля,
# потому что два разных приложения с пустыми экранами не должны совпадать.
KEYS_WEIGHT = 0.85
PACKAGE_WEIGHT = 0.15

# Порог «тот же экран» по умолчанию; для слияния слепков преград — строже.
THRESHOLD = 0.85
MERGE_THRESHOLD = 0.9

_SEP = "\x1f"


def _foreign(node, package: str) -> bool:
    """Узел чужого пакета (шторка, навбар) — не часть экрана приложения."""
    if not package:
        return False
    if node.package and node.package != package:
        return True
    rid = node.resource_id
    return bool(rid) and ":" in rid and not rid.startswith(package + ":") \
        and not node.package


def node_key(node) -> tuple:
    """Ключ узла без рамок: что это за элемент и в каком он состоянии."""
    return (node.resource_id, node.cls, node.text, node.description,
            bool(node.clickable), bool(getattr(node, "enabled", True)),
            bool(node.focused))


def fingerprint(nodes: list, package: str = "") -> dict:
    """Отпечаток экрана: пакет и отсортированные ключи (JSON-совместимо)."""
    keys = {_SEP.join(str(int(p) if isinstance(p, bool) else p) for p in node_key(n))
            for n in nodes if not _foreign(n, package)}
    return {"package": package or "", "keys": sorted(keys)}


def from_xml(xml: str, width: int, height: int, package: str = "") -> dict:
    """Отпечаток прямо из дампа; битый дамп даёт пустой отпечаток."""
    try:
        return fingerprint(tree.parse(xml, width, height), package)
    except Exception:  # noqa: BLE001 — без дампа отпечатка нет, это не авария
        return {"package": package or "", "keys": []}


def similarity(a: dict, b: dict) -> float:
    """Похожесть 0..1: Жаккар ключей × 0.85 + совпадение пакета × 0.15.

    Два пустых множества считаются одинаковыми (1.0 по ключам): сравнивать
    нечего, и отличие пакета всё равно снимет свою долю.
    """
    ka, kb = set(a.get("keys") or ()), set(b.get("keys") or ())
    jac = 1.0 if not ka and not kb else len(ka & kb) / len(ka | kb)
    same = 1.0 if (a.get("package") or "") == (b.get("package") or "") else 0.0
    return jac * KEYS_WEIGHT + same * PACKAGE_WEIGHT


def is_same(a: dict, b: dict, threshold: float = THRESHOLD) -> bool:
    return similarity(a, b) >= threshold


def percent(score: float) -> str:
    return f"{round(score * 100)}%"
