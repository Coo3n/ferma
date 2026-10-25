"""Что нейросеть не имеет права нажимать без человека.

Проверяет ЭТОТ код, а не модель: модель можно уговорить или она ошибётся, а
цена ошибки здесь — списанные деньги, отправленное сообщение, удалённый
аккаунт. Смотрим на два текста: цель шага (что просили нажать) и то, что
реально лежит под найденной точкой (дерево, при наличии — OCR). Совпало со
списком — слой молчит, решает человек в HELD.

Ложные срабатывания дёшевы (человек нажмёт «продолжить»), пропуск — нет,
поэтому совпадение идёт по началу слова и без снисхождений.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .. import config
from ..vision.synonyms import normalize

log = logging.getLogger("farm.vlm")

_HERE = Path(__file__).parent


def _prep(text: str) -> str:
    return normalize(str(text or "").lower().replace("ё", "е"))


def _read(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("список запретов %s не читается: %s", path.name, e)
        return {}
    return raw if isinstance(raw, dict) else {}


def classes() -> dict:
    """{класс: [регулярка начала слова, ...]} — встроенный список плюс data/vlm_deny.json."""
    merged: dict = {}
    for src in (_read(_HERE / "irreversible.json"), _read(Path(config.DATA_DIR) / "vlm_deny.json")):
        for name, phrases in src.items():
            if name.startswith("_") or not isinstance(phrases, list):
                continue
            merged.setdefault(name, []).extend(str(p) for p in phrases if str(p).strip())
    return {name: [re.compile(r"(?<![\w])" + re.escape(_prep(p))) for p in phrases]
            for name, phrases in merged.items()}


def irreversible(*texts) -> str:
    """Название запрещённого класса («оплата» …) или "" — можно."""
    cooked = [_prep(t) for t in texts if t]
    for name, patterns in classes().items():
        for text in cooked:
            if any(p.search(text) for p in patterns):
                return name
    return ""


def secret_goal(*texts) -> bool:
    """Цель про пароль/код/карту: такой экран нейросети не показываем."""
    words = [_prep(w) for w in _read(_HERE / "secret.json").get("words", [])]
    cooked = [_prep(t) for t in texts if t]
    return any(re.search(r"(?<![\w])" + re.escape(w), c) for w in words for c in cooked)


def secret_screen(nodes) -> bool:
    """На экране поле пароля или поле ввода кода в фокусе."""
    for n in nodes:
        if n.password:
            return True
        if n.focused and secret_goal(n.hint, n.text, n.description, n.resource_id):
            return True
    return False
