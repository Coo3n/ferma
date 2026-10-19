"""Проверка сценария до запуска: что сломается, ещё не тронув устройство.

В отличие от `normalize_steps` (первая же ошибка → 400) здесь ошибки
собираются списком и привязаны к шагу: конструктор подсвечивает каждый.
Чистая функция: внешние факты (какие блоки есть, какие пакеты стоят) приходят
аргументами, поэтому тест не требует ни диска, ни телефона.
"""
from __future__ import annotations

from ..context import is_weak_anchor
from . import steps as schema

LONG_SLEEP = 60


def validate(payload: dict, blocks: dict | None = None,
             packages: set | None = None, assets: set | None = None) -> dict:
    """{ok, errors[], warnings[]}; каждая запись {step, level, text}.

    `blocks` — {ключ: True, если блок загружается}; `packages` — установленные
    на устройстве пакеты (None — устройство не выбрано); `assets` — имена кропов,
    приехавших вместе с запросом.
    """
    out = {"errors": [], "warnings": []}

    def add(level, index, text):
        out["errors" if level == "error" else "warnings"].append(
            {"step": index, "level": level, "text": text})

    try:
        schema.normalize_meta(payload.get("meta"))
        params = schema.normalize_params(payload.get("params"))
    except schema.StepError as e:
        add("error", -1, str(e))
        params = {}

    raw = payload.get("steps")
    if not isinstance(raw, list):
        add("error", -1, "шаги должны быть списком")
        raw = []
    good = []
    for i, item in enumerate(raw):
        try:
            good.append((i, schema.normalize_step(item)))
        except schema.StepError as e:
            add("error", i, str(e))

    if not raw:
        add("warning", -1, "в сценарии нет шагов")

    for i, step in good:
        kind = step["kind"]
        name = step.get("param")
        if name and name not in params:
            add("error", i, f"параметр «{name}» не описан")
        if kind == "sleep" and step["args"].get("seconds", 0) > LONG_SLEEP:
            add("warning", i, f"пауза {step['args']['seconds']:g} с — очень долго")
        if kind == "click" and step.get("crop") is not None and assets is not None \
                and step["crop"] not in assets:
            add("error", i, f"кроп «{step['crop']}» не приложен — слой поиска "
                            "по картинке не сработает")
        if kind == "click" and not (step.get("texts") or step.get("crop")
                                    or step.get("point")) \
                and not step["selector"]["fallbacks"]:
            add("warning", i, "у клика один селектор без запасных слоёв: "
                              "при малейшем изменении экрана шаг упадёт")
        if kind == "expect" and is_weak_anchor(
                [{"a": a} for a in step.get("any") or []]):
            add("warning", i, "якорь опирается только на системную панель: он "
                              "совпадёт на любом экране и ничего не проверит")
        if kind == "branch":
            if not step["arms"]:
                add("error", i, "в развилке нет ветвей")
            for arm in step["arms"]:
                key = arm["run"]
                if key and blocks is not None and not blocks.get(key):
                    add("error", i, f"блок «{key}» ветки «{arm['name']}» "
                                    "не найден или не загружается")
        if kind in ("launch_app", "stop_app") and packages is not None \
                and not step.get("param") and step["args"]["package"] not in packages:
            add("warning", i, f"приложение {step['args']['package']} не установлено "
                              "на выбранном телефоне")
    if good and good[-1][1].get("optional"):
        add("warning", good[-1][0], "последний шаг необязателен — прогон "
                                    "пройдёт, даже если он не сработает")
    out["ok"] = not out["errors"]
    return out
