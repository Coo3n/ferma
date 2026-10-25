"""Снимки экрана."""
from __future__ import annotations

import base64
import io
import logging
import time

from .. import adb, config
from .fallback import from_u2
from .geometry import size

log = logging.getLogger("farm.capture")

DEFAULT_QUALITY = 80
ARTIFACT_QUALITY = 85


_stat = {"n": 0, "sum": 0.0}

# Маркеры ответа screencap на окно с FLAG_SECURE: команда не падает кодом, а
# печатает текст вместо PNG.
SECURE_MARKERS = (b"status: -1", b"failed", b"secure")
PREVIEW_MAX_WIDTH = 240   # кадры не шире — превью, флаг защиты не пишут
BLANK_MAX = 4   # самый яркий пиксель не выше — кадр считается чёрным

_secure_at: dict[str, tuple[bool, float]] = {}


def is_blank(frame) -> bool:
    """Весь кадр чёрный? Принимает PIL-картинку, JPEG/PNG-байты или массив numpy.

    Защищённое окно скриншот отдаёт чёрным прямоугольником, а не ошибкой.
    Проверяем по уменьшенной копии: целый кадр ради «есть ли хоть один
    светлый пиксель» читать незачем.
    """
    if isinstance(frame, (bytes, bytearray)):
        from PIL import Image
        img = Image.open(io.BytesIO(frame))
        img.draft("L", (64, 64))   # JPEG раскодируется сразу в уменьшенном виде
        frame = img
    if hasattr(frame, "getextrema"):
        small = frame.copy()
        small.thumbnail((64, 64))   # сначала уменьшаем, потом переводим в серый
        return small.convert("L").getextrema()[1] <= BLANK_MAX
    try:
        import numpy as np
    except ImportError:
        return False
    arr = np.asarray(frame)
    return arr.size > 0 and int(arr.max()) <= BLANK_MAX


def note_secure(serial: str, secure: bool) -> None:
    _secure_at[serial] = (secure, time.time())


def is_secure(serial: str) -> bool:
    """Последний кадр этого устройства был защищённым (и не старше SECURE_TTL).

    Срок нужен, чтобы флаг не залипал: ушли с защищённого окна, а кадров никто
    не снимал — через несколько секунд ему больше не верим.
    """
    secure, at = _secure_at.get(serial, (False, 0.0))
    return secure and time.time() - at <= config.SECURE_TTL


def _is_secure_reply(raw) -> bool:
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    head = bytes(raw[:200]).lower()
    return not head.startswith(b"\x89png") and any(m in head for m in SECURE_MARKERS)


def _note_time(path: str, started: float) -> None:
    """Среднее время захвата — в debug-лог раз в 50 кадров."""
    _stat["n"] += 1
    _stat["sum"] += time.time() - started
    if _stat["n"] % 50 == 0:
        log.debug("захват экрана: среднее %.0f мс за %d кадров (%s)",
                  _stat["sum"] / _stat["n"] * 1000, _stat["n"], path)


def _note_blank(serial: str, frame) -> None:
    """Чёрный кадр + пустой дамп = защищённое окно; чёрный кадр при живом
    дереве (видео, заставка) защитой не считаем. Дамп снимаем только для
    чёрного кадра, на обычных кадрах он не нужен."""
    if not is_blank(frame):
        note_secure(serial, False)
        return
    if is_secure(serial):
        return   # явный отказ screencap уже поставил флаг — дамп не нужен
    try:
        from .diagnostics import dump_hierarchy
        minimal = dump_hierarchy(serial).count("<node") <= 3
    except Exception:  # noqa: BLE001 — нет дампа: без доказательств флаг не ставим
        return   # и не гасим: явный отказ screencap уже мог его поставить
    if minimal:
        note_secure(serial, True)


def _device_jpeg(serial: str, max_width: int, quality: int) -> bytes | None:
    """Готовый JPEG с телефона: ужатие и кодирование делает само устройство.

    Без PNG-декода, ресайза и перекодирования в PIL — для потока и плиток это
    главная часть времени кадра. None — вызывающий откатывается на старый путь.
    """
    def grab(d):
        width = size(serial)[0]
        scale = min(1.0, max_width / width) if width else 1.0
        data = d.jsonrpc.takeScreenshot(scale, int(quality))
        return base64.b64decode(data) if data else None

    data = from_u2(serial, grab)
    return data if data and data[:2] == b"\xff\xd8" else None


def _screencap_image(serial: str):
    """PNG через adb. Ответ-отказ screencap (FLAG_SECURE) превращаем в чёрный
    кадр и помечаем устройство защищённым, а не роняем поток невнятной ошибкой."""
    from PIL import Image
    raw = adb.screencap_png(serial)
    if _is_secure_reply(raw):
        note_secure(serial, True)
        try:
            w, h = size(serial)
        except Exception:  # noqa: BLE001 — размер не обязателен для заглушки
            w, h = 360, 800
        return Image.new("RGB", (w or 360, h or 800))
    return Image.open(io.BytesIO(raw))


def screenshot(serial: str, max_width: int | None = None,
               quality: int = DEFAULT_QUALITY) -> bytes:
    """JPEG-байты текущего экрана."""
    from PIL import Image

    started = time.time()
    if max_width:
        data = _device_jpeg(serial, max_width, quality)
        if data:
            try:
                # Превью мелкое и частое; чёрное видео/заставка — не защита.
                if max_width > PREVIEW_MAX_WIDTH:
                    _note_blank(serial, data)
            except Exception:  # noqa: BLE001 — проверка не должна ронять кадр
                pass
            _note_time("device-jpeg", started)
            return data

    image = from_u2(serial, lambda d: d.screenshot())
    if image is None:
        image = _screencap_image(serial)

    image = image.convert("RGB")
    # Чёрный кадр сам по себе не признак защиты (видео, заставка, погашенный
    # экран); «защищён» ставит только явный отказ screencap (_screencap_image).
    if not max_width or max_width > PREVIEW_MAX_WIDTH:
        _note_blank(serial, image)
    if max_width and image.width > max_width:
        ratio = max_width / image.width
        # Для мелких превью LANCZOS по полному экрану — лишние десятки мс на
        # кадр × 40 телефонов; reducing_gap сначала грубо ужимает в разы.
        small = max_width <= 320
        image = image.resize((max_width, int(image.height * ratio)),
                             Image.BILINEAR if small else Image.LANCZOS,
                             reducing_gap=2.0 if small else None)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=False)
    _note_time("pillow", started)
    return buffer.getvalue()


def save_screenshot(serial: str, path) -> str:
    data = screenshot(serial, max_width=config.ARTIFACT_MAX_WIDTH,
                      quality=ARTIFACT_QUALITY)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)
