"""Ожидание, пока экран дорисуется.

Медленный девайс не успел отрисовать экран — клик уходит в пустоту. Два
одинаковых дампа иерархии подряд означают «дорисовано». dump, shot и sleep
подменяются в тестах, поэтому модуль проверяется без устройства.

Три уточнения к «двум одинаковым дампам»:
- спиннер/скелетон: на статичном кадре загрузка выглядит «стабильно», хотя
  контент ещё не пришёл — такой дамп стабильностью не считаем (`is_loading`);
- вечная анимация: XML меняется каждый тик, но картинка почти та же — запасной
  путь по пикселям (`frames_differ`);
- после свайпа важна только рамка цели, а не весь экран (`wait_target_stable`).
"""
from __future__ import annotations

import hashlib
import io
import re
import time
import xml.etree.ElementTree as ET

from .. import config
from .diagnostics import dump_hierarchy

# Только class/resource-id: текст «Loading» на кнопке — не индикатор загрузки.
_LOADING_RE = re.compile(
    r'(?:class|resource-id)="[^"]*(?:progressbar|shimmer|skeleton|loading)[^"]*"',
    re.IGNORECASE)
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
# Соответствие ключей селектора атрибутам дампа.
_ATTRS = {"text": "text", "resourceId": "resource-id", "description": "content-desc",
          "className": "class"}


def _fingerprint(xml: str) -> str:
    return hashlib.md5(xml.encode("utf-8", "replace")).hexdigest()


def is_loading(xml: str) -> bool:
    """В дампе есть индикатор загрузки (ProgressBar / Shimmer / skeleton / loading)."""
    return bool(xml) and _LOADING_RE.search(xml) is not None


def frames_differ(a, b, threshold: float | None = None) -> bool:
    """Кадры (байты PNG/JPEG) отличаются сильнее порога (средняя разница 0..1).

    Кадр сжимается до маленького серого — шум кодека и часы в углу не должны
    считаться сменой экрана. Нет numpy — считаем на PIL; нет и его, или кадр не
    разобрался — честно сравниваем байты: деградация без падения.
    """
    threshold = config.PIXEL_DIFF_THRESHOLD if threshold is None else threshold
    if a is None or b is None:
        return True
    if a == b:
        return False
    try:
        from PIL import Image
        small = []
        for raw in (a, b):
            im = Image.open(io.BytesIO(raw)).convert("L").resize((48, 48))
            small.append(im)
        try:
            import numpy as np
            diff = float(np.abs(np.asarray(small[0], dtype="int16")
                                - np.asarray(small[1], dtype="int16")).mean()) / 255.0
        except ImportError:
            pa, pb = small[0].tobytes(), small[1].tobytes()
            diff = sum(abs(x - y) for x, y in zip(pa, pb)) / (len(pa) * 255.0)
        return diff > threshold
    except Exception:  # noqa: BLE001 — кадр не разобрался: байты уже не равны
        return True


def find_bounds(xml: str, **sel):
    """Рамка (l, t, r, b) первого узла, подходящего под селектор, или None.

    Понимает text / resourceId / description / className (точное совпадение) и
    textContains. Чистая функция: дамп приходит строкой.
    """
    if not xml or not sel:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    for node in root.iter():
        ok = True
        for key, want in sel.items():
            if key == "textContains":
                ok = str(want) in node.get("text", "")
            elif key in _ATTRS:
                ok = node.get(_ATTRS[key], "") == str(want)
            else:
                continue   # незнакомый ключ селектора не должен «убить» поиск
            if not ok:
                break
        if ok:
            m = _BOUNDS_RE.fullmatch(node.get("bounds", ""))
            if m:
                return tuple(int(v) for v in m.groups())
    return None


def wait_stable(serial: str, timeout: float | None = None,
                quiet: float | None = None, dump=None, sleep=time.sleep,
                shot=None) -> bool:
    """True — экран стабилен; False — таймаут или дамп не снялся.

    `shot` — снимок экрана (байты) для запасного пути: когда XML так и не
    замер (вечная анимация), но два кадра подряд почти не отличаются, экран
    считаем стабильным. По умолчанию кадр берётся с устройства, только если dump
    не подменён (в тестах телефона нет).
    """
    timeout = config.SETTLE_TIMEOUT if timeout is None else timeout
    quiet = config.SETTLE_QUIET if quiet is None else quiet
    if shot is None and dump is None and config.SETTLE_PIXEL:
        shot = lambda: _device_shot(serial)  # noqa: E731
    dump = dump or (lambda: dump_hierarchy(serial))
    deadline = time.monotonic() + timeout
    try:
        xml = dump()
    except Exception:  # noqa: BLE001 — дамп не снялся, шагу не мешаем
        return False
    last = _fingerprint(xml)
    loading = is_loading(xml)
    while time.monotonic() < deadline:
        sleep(quiet)
        try:
            xml = dump()
        except Exception:  # noqa: BLE001
            return False
        current = _fingerprint(xml)
        loading = is_loading(xml)
        # Спиннер на месте — «стабильно» обманчиво, ждём, пока он уйдёт.
        if current == last and not loading:
            return True
        last = current
    if shot is not None and not loading:
        return _pixels_calm(shot, sleep, quiet)
    return False


def _pixels_calm(shot, sleep, quiet: float) -> bool:
    try:
        first = shot()
        sleep(quiet)
        return not frames_differ(first, shot())
    except Exception:  # noqa: BLE001
        return False


def _device_shot(serial: str):
    from .capture import screenshot
    return screenshot(serial, max_width=160)


def wait_target_stable(serial: str, locate, timeout: float | None = None,
                       quiet: float | None = None, dump=None, sleep=time.sleep):
    """Рамка цели не менялась между двумя свежими дампами подряд.

    После свайпа лента ещё доезжает, но ждать, пока замрёт ВЕСЬ экран, незачем
    (там вечно что-то дорисовывается): клику нужна только цель. `locate(xml)`
    даёт рамку или None. Не дождались — возвращаем последнюю известную рамку,
    не падаем; цели нет в двух дампах подряд — ждать нечего, сразу None.
    """
    timeout = config.TARGET_STABLE_TIMEOUT if timeout is None else timeout
    quiet = config.SETTLE_QUIET if quiet is None else quiet
    dump = dump or (lambda: dump_hierarchy(serial))
    deadline = time.monotonic() + timeout
    last = None
    missing = 0
    first = True
    while True:
        try:
            rect = locate(dump())
        except Exception:  # noqa: BLE001
            return last
        if rect is None:
            missing += 1
            if missing >= 2:
                return None
        else:
            missing = 0
            if not first and rect == last:
                return rect
            last = rect
        first = False
        if time.monotonic() >= deadline:
            return last
        sleep(quiet)
