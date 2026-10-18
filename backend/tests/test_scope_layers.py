"""Запасные слои (текст, OCR, картинка, точка) знают «внутри» и «рядом с».

Владелец: «лайк под постом Ивана». Селектор устарел — спасает слой текста или
картинки; если он нажмёт первый попавшийся лайк, это хуже, чем промах.
"""
import pytest

from farm import resolve
from farm.context import HOLD_GO, StepFailed, normalize_target
from farm.recorder import codegen, steps
from farm.vision import ocr as ocr_mod
from farm.vision import template as tpl_mod
from test_scope import Ctx

LIKE2 = (0.07, 0.57)          # лайк под постом Ивана
STORIES_LIKE = (0.05, 0.975)  # лайк в полоске историй
IVAN = (0.26, 0.3675)         # центр надписи «Иван Петров»
REL = (-0.19, 0.2025)         # лайк Ивана от центра его имени
MISS = [{"text": "нет такого"}]


# ------------------------------------------------ слой текста по дереву

def test_текст_рядом_с_ориентиром():
    ctx = Ctx()
    ctx.click_target(sel=MISS, text=["Нравится"], near={"text": "Иван Петров"}, timeout=0)
    assert ctx.taps == [LIKE2]


def test_текст_внутри_контейнера():
    ctx = Ctx()
    ctx.click_target(sel=MISS, text=["Нравится"], within={"resourceId": "app:id/stories"},
                     timeout=0)
    assert ctx.taps == [STORIES_LIKE]


def test_текст_без_места_как_раньше():
    ctx = U2Ctx()
    ctx.click_target(sel=MISS, text=["Нравится"], timeout=0)
    assert ctx.taps == [(0.07, 0.27)]   # первый лайк — под постом Анны


def test_текст_вне_контейнера_не_нажимается():
    ctx = Ctx()
    with pytest.raises(StepFailed):
        ctx.click_target(sel=MISS, text=["Анна"], within={"resourceId": "app:id/stories"},
                         timeout=0)
    assert ctx.taps == []


# ------------------------------------------------ OCR

class U2Ctx(Ctx):
    """Без места цель ищется через u2 — здесь он ничего не находит."""

    def find(self, timeout=10, **selector):
        return None


class Box:
    def __init__(self, text, cx, cy):
        self.text, self.cx, self.cy = text, cx, cy


@pytest.fixture
def fake_ocr(monkeypatch):
    boxes = [Box("Лайк", 0.07, 0.27), Box("Лайк", 0.07, 0.57), Box("Лайк", 0.05, 0.975)]
    monkeypatch.setattr(ocr_mod, "backend", lambda: "fake")
    monkeypatch.setattr(ocr_mod, "ocr", lambda data: boxes)
    monkeypatch.setattr(Ctx, "screen_bytes", lambda self: b"png", raising=False)


def test_ocr_рядом_с_ориентиром(fake_ocr):
    """Зрение дерева не знает: решает смещение от ориентира, записанное у шага."""
    ctx = Ctx()
    ctx.click_target(sel=MISS, text=["Лайк"], near={"text": "Иван Петров"}, at_rel=REL,
                     timeout=0)
    assert ctx.taps == [LIKE2]


def test_ocr_рядом_с_без_смещения_ближайший_к_ориентиру(fake_ocr):
    ctx = Ctx()
    # Без смещения — просто ближе по экрану к имени Олега (это лайк выше).
    ctx.click_target(sel=MISS, text=["Лайк"], near={"text": "Олег"}, timeout=0)
    assert ctx.taps == [LIKE2]


def test_ocr_внутри_контейнера(fake_ocr):
    ctx = Ctx()
    ctx.click_target(sel=MISS, text=["Лайк"], within={"resourceId": "app:id/stories"},
                     timeout=0)
    assert ctx.taps == [STORIES_LIKE]


# ------------------------------------------------ картинка

@pytest.fixture
def fake_tpl(monkeypatch):
    calls = []

    def find(screen, data, base_scale=1.0, near=None, with_count=False, region=None):
        calls.append({"near": near, "region": region})
        return (0.5, 0.5, 0.9, 1) if with_count else (0.5, 0.5, 0.9)

    monkeypatch.setattr(tpl_mod, "available", lambda: True)
    monkeypatch.setattr(tpl_mod, "find", find)
    monkeypatch.setattr(Ctx, "screen_bytes", lambda self: b"png", raising=False)
    monkeypatch.setattr(Ctx, "asset", lambda self, name: (b"crop", 1.0), raising=False)
    return calls


def test_картинка_ищется_в_рамке_контейнера(fake_tpl):
    ctx = Ctx()
    ctx.click_target(sel=MISS, img="01_click.png", within={"resourceId": "app:id/stories"},
                     timeout=0)
    assert fake_tpl[0]["region"] == (0.0, 0.95, 1.0, 1.0)
    assert ctx.taps == [(0.5, 0.5)]


def test_картинка_рядом_с_берёт_ближайшую_к_ориентиру(fake_tpl):
    ctx = Ctx()
    ctx.click_target(sel=MISS, img="01_click.png", near={"text": "Иван Петров"}, timeout=0)
    assert fake_tpl[0]["near"] == pytest.approx(IVAN)
    assert fake_tpl[0]["region"] is None


def test_картинка_рядом_с_и_смещение_точки(fake_tpl):
    ctx = Ctx()
    ctx.click_target(sel=MISS, img="01_click.png", near={"text": "Иван Петров"},
                     at_rel=REL, timeout=0)
    assert fake_tpl[0]["near"] == pytest.approx(LIKE2)


def test_картинка_без_места_как_раньше(fake_tpl):
    ctx = U2Ctx()
    ctx.click_target(sel=MISS, img="01_click.png", at=(0.1, 0.2), timeout=0)
    assert fake_tpl[0] == {"near": (0.1, 0.2), "region": None}


@pytest.mark.skipif(not tpl_mod.available(), reason="opencv не установлен")
def test_настоящий_шаблон_ищет_только_в_рамке():
    """Три одинаковые иконки: в рамке нижней трети — только нижняя."""
    import io

    from PIL import Image, ImageDraw
    screen = Image.new("RGB", (400, 800), "white")
    draw = ImageDraw.Draw(screen)
    for y in (100, 400, 700):
        draw.ellipse((40, y - 20, 80, y + 20), fill="black")
        draw.rectangle((55, y - 8, 65, y + 8), fill="white")
    crop = screen.crop((30, 70, 90, 130))

    def png(im):
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    cx, cy, _ = tpl_mod.find(png(screen), png(crop), region=(0.0, 0.66, 1.0, 1.0))
    assert abs(cy - 700 / 800) < 0.02 and abs(cx - 60 / 400) < 0.02
    cx, cy, _, n = tpl_mod.find(png(screen), png(crop), region=(0.0, 0.3, 1.0, 0.7),
                                near=(0.1, 0.1), with_count=True)
    assert n == 1 and abs(cy - 400 / 800) < 0.02
    # рамка меньше шаблона — не нашлось, а не исключение
    assert tpl_mod.find(png(screen), png(crop), region=(0.0, 0.0, 0.05, 0.05)) is None


# ------------------------------------------------ точка

def test_точка_рядом_с_считается_от_ориентира():
    ctx = Ctx()
    ctx.click_target(sel=MISS, near={"text": "Иван Петров"}, at_rel=REL,
                     timeout=0)
    assert ctx.taps == [LIKE2]


def test_точка_внутри_считается_от_рамки_контейнера():
    ctx = Ctx()
    ctx.click_target(sel=MISS, within={"resourceId": "app:id/stories"}, at_rel=(0.05, 0.75),
                     timeout=0)
    assert ctx.taps == [(0.05, 0.988)]


def test_нет_ориентира_точка_не_нажимается():
    ctx = Ctx()
    with pytest.raises(StepFailed) as e:
        ctx.click_target(sel=MISS, near={"text": "Мария"}, at_rel=(0.0, 0.1), at=(0.5, 0.5),
                         timeout=0)
    assert ctx.taps == []
    assert "не найден ориентир" in str(e.value)


def test_с_местом_абсолютная_точка_не_нажимается():
    """Без смещения от ориентира старая точка экрана — не «рядом с»: промах."""
    ctx = Ctx()
    with pytest.raises(StepFailed):
        ctx.click_target(sel=MISS, near={"text": "Иван Петров"}, at=(0.5, 0.5), timeout=0)
    assert ctx.taps == []


def test_без_места_абсолютная_точка_как_раньше():
    ctx = U2Ctx()
    ctx.click_target(sel=MISS, at=(0.5, 0.5), timeout=0)
    assert ctx.taps == [(0.5, 0.5)]


def test_точка_от_места_спрашивает_как_вслепую():
    вопросы = []
    ctx = Ctx(hold=lambda что, **kw: вопросы.append(что) or HOLD_GO)
    ctx.click_target(sel=MISS, near={"text": "Иван Петров"}, at_rel=REL,
                     timeout=0)
    assert ctx.taps == [LIKE2] and вопросы and "вслепую" in вопросы[0]


def test_чистый_расчёт_точки_от_места():
    box = (0.0, 0.5, 0.5, 1.0)
    assert resolve.point_from(("within", box), (0.5, 0.5)) == pytest.approx((0.25, 0.75))
    assert resolve.point_from(("near", (0.2, 0.2)), (0.1, -0.1)) == pytest.approx((0.3, 0.1))


# ------------------------------------------------ формат рецепта и кодоген

def click(**extra):
    raw = {"kind": "click", "selector": {"call": "click", "args": 'resourceId="app:id/like"'}}
    raw.update(extra)
    return raw


def test_point_rel_проходит_проверку():
    st = steps.normalize_step(click(near='text="Иван"', point_rel=[-0.19, -0.165]))
    assert st["point_rel"] == [-0.19, -0.165]
    st = steps.normalize_step(click(within='resourceId="b"', point_rel=[0.5, 0.25]))
    assert st["point_rel"] == [0.5, 0.25]
    assert "point_rel" not in steps.normalize_step(click())


@pytest.mark.parametrize("extra", [
    {"point_rel": [0.1, 0.1]},                                   # без места
    {"within": 'resourceId="b"', "point_rel": [1.5, 0.1]},       # вне рамки
    {"near": 'text="a"', "point_rel": [-2, 0]},                  # дальше экрана
    {"near": 'text="a"', "point_rel": "x"},
])
def test_плохой_point_rel_отвергается(extra):
    with pytest.raises(steps.StepError):
        steps.normalize_step(click(**extra))


def _line(step):
    src = codegen.render({"name": "n", "watch_popups": False}, {}, [steps.normalize_step(step)])
    compile(src, "x.py", "exec")
    return src.strip().splitlines()[-1].strip()


def test_кодоген_point_rel():
    assert _line(click(near='text="Иван"', point=[0.07, 0.57], point_rel=[-0.19, 0.2025])) == (
        'ctx.click_target(sel=[dict(resourceId="app:id/like")], at=(0.07, 0.57), '
        'at_rel=(-0.19, 0.203), near=dict(text="Иван"))')


def test_рамка_в_пиксели_чистая_функция():
    assert tpl_mod.crop_box((0.0, 0.95, 1.0, 1.0), 1000, 2000) == (0, 1900, 1000, 2000)
    # за краем экрана — обрезается, перевёрнутая — пустая, а не отрицательная
    assert tpl_mod.crop_box((-0.1, 0.5, 1.2, 1.5), 100, 100) == (0, 50, 100, 100)
    assert tpl_mod.crop_box((0.6, 0.6, 0.2, 0.2), 100, 100) == (60, 60, 60, 60)


def test_патч_цели_несёт_смещение():
    assert normalize_target({"sel": [{"text": "x"}], "at_rel": [0.1, -0.2]})["at_rel"] == [0.1, -0.2]
    with pytest.raises(ValueError):
        normalize_target({"sel": [{"text": "x"}], "at_rel": [3, 0]})
