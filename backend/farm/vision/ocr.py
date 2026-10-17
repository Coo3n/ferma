"""OCR: Apple Vision на macOS (пакет ocrmac), tesseract запасным.

Бэкенд выбирается один раз и лениво. Без зависимостей ферма работает — просто
слой OCR в резолвере выключен.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass


@dataclass
class Box:
    text: str
    cx: float   # центр, нормализованный 0..1
    cy: float
    conf: float


_backend: str | None = None  # None — ещё не выбирали; "" — ничего нет


def backend() -> str:
    global _backend
    if _backend is None:
        _backend = ""
        if sys.platform == "darwin":
            try:
                from ocrmac import ocrmac  # noqa: F401
                _backend = "vision"
            except ImportError:
                pass
        if not _backend:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                _backend = "tesseract"
            except Exception:  # noqa: BLE001 — нет пакета или самого бинаря
                pass
    return _backend


def ocr(image_bytes: bytes) -> list:
    name = backend()
    if name == "vision":
        return _vision(image_bytes)
    if name == "tesseract":
        return _tesseract(image_bytes)
    return []


def _vision(image_bytes: bytes) -> list:
    from ocrmac import ocrmac
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    out = []
    # ocrmac отдаёт (text, confidence, (x, y, w, h)); bbox нормализован, начало
    # координат — левый НИЖНИЙ угол (так устроен Vision framework).
    for text, conf, (x, y, w, h) in ocrmac.OCR(image).recognize():
        out.append(Box(text=text, cx=x + w / 2, cy=1 - (y + h / 2), conf=float(conf)))
    return out


def _tesseract(image_bytes: bytes) -> list:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    data = pytesseract.image_to_data(image, lang="rus+eng",
                                     output_type=pytesseract.Output.DICT)
    out = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        cx = (data["left"][i] + data["width"][i] / 2) / image.width
        cy = (data["top"][i] + data["height"][i] / 2) / image.height
        out.append(Box(text=text, cx=cx, cy=cy, conf=conf / 100.0))
    return out
