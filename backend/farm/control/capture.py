"""Снимки экрана."""
from __future__ import annotations

import io

from .. import adb, config
from .fallback import from_u2

DEFAULT_QUALITY = 80
ARTIFACT_QUALITY = 85


def screenshot(serial: str, max_width: int | None = None,
               quality: int = DEFAULT_QUALITY) -> bytes:
    """JPEG-байты текущего экрана."""
    from PIL import Image

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
    return buffer.getvalue()


def save_screenshot(serial: str, path) -> str:
    data = screenshot(serial, max_width=config.ARTIFACT_MAX_WIDTH,
                      quality=ARTIFACT_QUALITY)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)
