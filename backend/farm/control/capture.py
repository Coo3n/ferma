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


def _note_time(path: str, started: float) -> None:
    """Среднее время захвата — в debug-лог раз в 50 кадров."""
    _stat["n"] += 1
    _stat["sum"] += time.time() - started
    if _stat["n"] % 50 == 0:
        log.debug("захват экрана: среднее %.0f мс за %d кадров (%s)",
                  _stat["sum"] / _stat["n"] * 1000, _stat["n"], path)


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


def screenshot(serial: str, max_width: int | None = None,
               quality: int = DEFAULT_QUALITY) -> bytes:
    """JPEG-байты текущего экрана."""
    from PIL import Image

    started = time.time()
    if max_width:
        data = _device_jpeg(serial, max_width, quality)
        if data:
            _note_time("device-jpeg", started)
            return data

    image = from_u2(serial, lambda d: d.screenshot())
    if image is None:
        image = Image.open(io.BytesIO(adb.screencap_png(serial)))

    image = image.convert("RGB")
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
