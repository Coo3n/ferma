"""Слепок преграды — что помешало сценарию и как это опознать потом.

Снимается в момент падения. Причина в тайминге: пока человек дойдёт до
журнала и нажмёт «научить обходить», устройство уже заберёт следующая задача
из очереди и экран сменится. Поэтому условие («как узнать эту преграду»)
фиксируется здесь и сейчас, а действие («что с ней делать») человек покажет
когда угодно и хоть на другом устройстве.

Модуль не знает про adb: на входе XML-дамп, на выходе словарь. Отсюда и
тестируемость без телефона — как у ui/tree.py.
"""
from __future__ import annotations

from .ui import tree

MAX_CANDIDATES = 5
MAX_TEXTS = 8
TEXT_MIN = 3      # «ОК» и «Да» есть на любом экране, опознавать по ним нечего
TEXT_MAX = 60     # длинная простыня — это контент, а не признак экрана

# Доля экрана, выше которой узел считается каркасом приложения, а не
# признаком экрана. На живом приложении пять кандидатов подряд были ровно
# 100% экрана (action_bar_root, mainContentRoot, fragmentTabContainer…) — и
# присутствовали одинаково и на экране ошибки, и на рабочем каталоге.
# Условие по такому узлу истинно всегда, то есть не опознаёт ничего.
FRAME_AREA = 0.9


def _foreign(resource_id: str, package: str) -> bool:
    """Узел принадлежит не тому приложению, чью преграду мы описываем.

    Дамп включает системную шторку: часы, статус-бар, кнопки навигации. На
    живом приложении все пять кандидатов оказались из com.android.systemui —
    страж по такому условию срабатывал бы на каждом экране любого приложения,
    то есть был бы всегда истинным и бесполезным. Часы туда же: «14:22» как
    признак экрана живёт одну минуту.
    """
    if not package or not resource_id:
        return False
    return not resource_id.startswith(package + ":")


def _label(selector: dict) -> str:
    """Подпись для человека: условие он выбирает глазами, а не по ключу."""
    if "resourceId" in selector:
        return f"по идентификатору: {selector['resourceId'].split('/')[-1]}"
    if "textContains" in selector:
        return f"по тексту: «{selector['textContains']}»"
    if "descriptionContains" in selector:
        return f"по описанию: «{selector['descriptionContains']}»"
    return str(selector)


def capture(xml: str, width: int, height: int, package: str = "") -> dict:
    """Слепок экрана-преграды: пакет, тексты и кандидаты в условие стража."""
    try:
        nodes = tree.parse(xml, width, height)
    except Exception:  # noqa: BLE001 — дамп битый, слепок всё равно полезен пакетом
        nodes = []

    texts, by_id, by_text, by_desc, by_frame = [], [], [], [], []
    for node in nodes:
        rid = (node.resource_id or "").strip()
        text = (node.text or "").strip()
        desc = (node.description or "").strip()

        # Узел чужого приложения (шторка, навбар) не описывает нашу преграду
        # ни идентификатором, ни текстом.
        if _foreign(rid, package):
            continue

        if text and text not in texts:
            texts.append(text)
        # resourceId первым: он один не зависит от локали, а преграду ловим
        # на устройствах с разным языком
        if rid and not any(c.get("resourceId") == rid for c in by_id):
            # каркас не выбрасываем совсем — кладём в хвост, вдруг больше нечего
            (by_frame if node.area > FRAME_AREA else by_id).append({"resourceId": rid})
        if TEXT_MIN <= len(text) <= TEXT_MAX and not any(
                c.get("textContains") == text for c in by_text):
            by_text.append({"textContains": text})
        if TEXT_MIN <= len(desc) <= TEXT_MAX and not any(
                c.get("descriptionContains") == desc for c in by_desc):
            by_desc.append({"descriptionContains": desc})

    отобрано = (by_id + by_text + by_desc + by_frame)[:MAX_CANDIDATES]
    return {
        "package": package,
        "texts": texts[:MAX_TEXTS],
        "candidates": [{"selector": s, "label": _label(s)} for s in отобрано],
    }


def _key(преграда: dict) -> str:
    """Опознавательный ключ преграды: первый кандидат.

    Одна и та же преграда попадается на многих устройствах — в списке она
    должна быть одной строкой со счётчиком, а не двадцатью одинаковыми.
    """
    кандидаты = преграда.get("candidates") or []
    return str(sorted(кандидаты[0]["selector"].items())) if кандидаты else ""


def uncovered(преграды: list, rules: list) -> list:
    """Преграды, на которые ещё нет отвода — самое ценное, что знает ферма.

    Она видела их в бою, но обходить не умеет. Это список дел, а не отчёт.
    Совпадение считаем по точному равенству селекторов: правило писалось из
    того же слепка, так что расхождение означает другую преграду.
    """
    закрыты = set()
    for rule in rules or []:
        for sel in (rule.get("when") or {}).get("any") or []:
            закрыты.add(str(sorted(sel.items())))

    собрано: dict[str, dict] = {}
    for преграда in преграды or []:
        ключ = _key(преграда)
        if not ключ or ключ in закрыты:
            continue
        обойдена = bool(преграда.get("escaped"))
        if ключ in собрано:
            собрано[ключ]["hits"] += 1
            собрано[ключ]["escapes" if обойдена else "fails"] += 1
            continue
        собрано[ключ] = {
            "texts": преграда.get("texts") or [],
            "package": преграда.get("package") or "",
            "candidates": преграда.get("candidates") or [],
            # Задача и имя файла нужны для обучения: слепок лежит в её
            # артефактах, и кнопка «научить» без них никуда не ведёт.
            "job": преграда.get("job") or "",
            "file": преграда.get("file") or "obstacle.json",
            "hits": 1,
            # Одну и ту же преграду ферма то роняет, то обходит вслепую —
            # разница важна: во втором случае прогоны доезжают, и по журналу
            # задач такой преграды не видно вообще.
            "escapes": 1 if обойдена else 0,
            "fails": 0 if обойдена else 1,
        }
    # чаще всего мешает — первым: с этого и стоит начинать
    return sorted(собрано.values(), key=lambda o: -o["hits"])
