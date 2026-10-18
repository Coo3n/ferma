"""Golden-тесты зрения. Пропускаются, когда vision-зависимости не стоят."""
import io

import pytest

from farm.vision import ocr, template


def шрифт(size=48):
    """Настоящий шрифт, если он есть: дефолтный битмап OCR распознаёт плохо."""
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def картинка_с_текстом(text="Login", size=(400, 160)):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((40, 50), text, fill="black", font=шрифт())
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_бэкенд_всегда_отвечает_строкой():
    assert isinstance(ocr.backend(), str)


def test_без_бэкенда_ocr_возвращает_пусто(monkeypatch):
    monkeypatch.setattr(ocr, "_backend", "")
    assert ocr.ocr(b"whatever") == []


@pytest.mark.skipif(not ocr.backend(), reason="OCR-бэкенд не установлен")
def test_ocr_находит_нарисованный_текст():
    boxes = ocr.ocr(картинка_с_текстом("Login"))
    hits = [b for b in boxes if "login" in b.text.casefold()]
    assert hits, f"OCR не нашёл текст: {boxes}"
    assert 0.0 < hits[0].cx < 1.0 and 0.0 < hits[0].cy < 1.0


def png(image):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def экран_и_кроп(scale=1.0):
    """Синтетика: «кнопка» на сером фоне; кроп кнопки — шаблон."""
    from PIL import Image, ImageDraw
    screen = Image.new("RGB", (400, 800), (200, 200, 200))
    draw = ImageDraw.Draw(screen)
    draw.rectangle((150, 500, 250, 560), fill=(30, 90, 200))
    draw.ellipse((180, 515, 220, 545), fill=(250, 220, 40))
    crop = screen.crop((150, 500, 250, 560))
    if scale != 1.0:
        screen = screen.resize((int(400 * scale), int(800 * scale)))
    return png(screen), png(crop)


def test_available_всегда_отвечает_булевым():
    assert isinstance(template.available(), bool)


def test_scales_for_чистая_функция_без_opencv():
    """Клэмп ограничивает отклонение шага, а не итоговый масштаб — иначе

    базовый масштаб (шаг 1.0) обрезается диапазоном 0.7–1.3 и никогда не
    пробуется. base_scale=1.5 — типичная пара устройств фермы (запись на
    720p, прогон на 1080p): раньше [1.5*0.85, 1.5*1.0, 1.5*1.15], клэмпнутые
    абсолютно, давали [1.275, 1.3, 1.3] — базовый 1.5 не пробовался вовсе.
    """
    assert template.scales_for(1.5) == [1.5 * 0.85, 1.5 * 1.0, 1.5 * 1.15]
    assert 1.5 in template.scales_for(1.5)


def test_scales_for_экстремальный_base_scale_не_убивает_слой():
    """base_scale=2.25 раньше давал три одинаковых клэмпнутых прогона

    (1.3, 1.3, 1.3) — слой становился мёртвым.
    """
    scales = template.scales_for(2.25)
    assert len(set(scales)) == 3


def test_scales_for_базовый_1_не_меняет_поведение():
    assert template.scales_for(1.0) == list(template.SCALE_STEPS)


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_шаблон_найден_на_том_же_масштабе():
    screen, crop = экран_и_кроп()
    hit = template.find(screen, crop)
    assert hit is not None
    cx, cy, score = hit
    assert abs(cx - 0.5) < 0.03 and abs(cy - 530 / 800) < 0.03
    assert score >= template.THRESHOLD


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_шаблон_найден_на_другом_разрешении():
    screen, crop = экран_и_кроп(scale=1.2)
    hit = template.find(screen, crop, base_scale=1.2)
    assert hit is not None and abs(hit[0] - 0.5) < 0.03


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_отсутствующий_шаблон_даёт_None():
    from PIL import Image
    _, crop = экран_и_кроп()
    assert template.find(png(Image.new("RGB", (400, 800), "white")), crop) is None


@pytest.mark.skipif(not template.available(), reason="opencv не установлен")
def test_три_одинаковые_иконки_берётся_ближайшая_к_месту_записи():
    """Лайки в ленте одинаковы: лучший балл — случайность, решает место записи."""
    from PIL import Image, ImageDraw
    screen = Image.new("RGB", (400, 800), "white")
    draw = ImageDraw.Draw(screen)
    for y in (100, 400, 700):
        draw.ellipse((40, y - 20, 80, y + 20), fill="black")
        draw.rectangle((55, y - 8, 65, y + 8), fill="white")
    crop = screen.crop((30, 370, 90, 430))
    hit = template.find(png(screen), png(crop), near=(0.15, 0.85), with_count=True)
    assert hit is not None
    cx, cy, score, count = hit
    assert count == 3
    assert abs(cy - 700 / 800) < 0.02 and abs(cx - 60 / 400) < 0.02
    # без места — по-старому: лучший балл, три числа
    assert len(template.find(png(screen), png(crop))) == 3
