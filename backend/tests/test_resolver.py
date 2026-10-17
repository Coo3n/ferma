"""Резолвер: сопоставление текста и порядок слоёв. Устройство не нужно."""
import pytest

from farm import resolve
from farm.vision import synonyms


def test_синонимы_работают_в_обе_стороны():
    assert "allow" in synonyms.expand("Разрешить")
    assert "разрешить" in synonyms.expand("ALLOW")
    assert synonyms.expand("нечто уникальное") == {"нечто уникальное"}


ЭЛЕМЕНТЫ = [("Вход в аккаунт", 0.5, 0.2), ("Войти", 0.5, 0.8), ("Отмена", 0.5, 0.9)]


def test_точное_совпадение_бьёт_вхождение():
    assert resolve.match_text(ЭЛЕМЕНТЫ, ["Войти"]) == ("Войти", 0.5, 0.8)


def test_вхождение_когда_точного_нет():
    assert resolve.match_text(ЭЛЕМЕНТЫ, ["Вход"]) == ("Вход в аккаунт", 0.5, 0.2)


def test_совпадение_по_синониму():
    assert resolve.match_text([("Allow", 0.5, 0.7)], ["Разрешить"]) == ("Allow", 0.5, 0.7)


def test_шум_ocr_переживается_нормализацией_гомоглифов():
    # латинская «o» вместо кириллической — типичная ошибка распознавания
    assert resolve.match_text([("Вoйти", 0.5, 0.8)], ["Войти"]) == ("Вoйти", 0.5, 0.8)


def test_вхождение_берёт_кратчайший_а_не_первый():
    """Раньше пас вхождения возвращал первый узел в порядке дерева.

    Здесь оба узла содержат «cookie» как подстроку (ни один не совпадает
    точно), но первый в списке — длинная фраза со ссылкой на политику,
    а не искомая короткая кнопка.
    """
    элементы = [("I agree to the cookie policy and terms", 0.1, 0.1),
                ("Accept cookie", 0.2, 0.2)]
    assert resolve.match_text(элементы, ["cookie"]) == ("Accept cookie", 0.2, 0.2)


def test_короткий_вариант_не_цепляется_к_длинной_фразе():
    """«ok»/«да»/«нет» короче 4 символов не участвуют в пасе вхождения —

    иначе они цепляются к середине любой длинной фразы, где случайно
    встретилась такая подстрока.
    """
    assert resolve.match_text([("Cookie policy", 0.3, 0.2)], ["OK"]) is None


def test_cookie_баннер_не_уходит_по_ссылке_на_политику():
    """Проверено эмпирически: normalize("cookie policy") содержит «оk»

    (гомоглиф o→о), поэтому пас вхождения раньше отдавал первый узел —
    ссылку на политику — вместо кнопки cookie-баннера.
    """
    found = resolve.match_text(
        [("Cookie policy", 0.3, 0.2), ("Ok, got it", 0.5, 0.9)], ["OK"])
    assert found != ("Cookie policy", 0.3, 0.2)


def test_далёкий_текст_не_совпадает():
    assert resolve.match_text([("Настройки", 0.5, 0.5)], ["Войти"]) is None


def test_вход_не_путается_с_выходом():
    """Ключевой тест безопасности: «Войти» и «Выйти» нельзя перепутать.

    difflib даёт «войти»/«вoйти» (шум OCR) и «войти»/«выйти» (разные
    действия!) одинаковые 0.8 — порогом их не разделить. Разделяет
    нормализация гомоглифов: шум схлопывается в точное совпадение, а
    «Выйти» остаётся за порогом нечёткости.
    """
    assert resolve.match_text([("Выйти", 0.5, 0.8)], ["Войти"]) is None


ДАМП = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node text="Войти" resource-id="" class="android.widget.Button"
        content-desc="" bounds="[100,700][300,780]" />
  <node text="" resource-id="" class="android.widget.TextView"
        content-desc="Настройки" bounds="[0,0][100,80]" />
</hierarchy>"""


class ФейкЭлемент:
    info = {"bounds": {"left": 400, "top": 400, "right": 600, "bottom": 500}}


class ФейкCtx:
    def __init__(self, found=None, dump="<hierarchy/>", shot=b"", asset=(None, 1.0)):
        self.found = found
        self.dump = dump
        self.shot = shot
        self._asset = asset
        self.size = (1000, 2000)
        self.lines = []

    def find(self, timeout=10, **sel):
        return self.found

    def dump_hierarchy(self):
        return self.dump

    def screen_bytes(self):
        return self.shot

    def asset(self, name):
        return self._asset

    def check_cancel(self):
        pass

    def log(self, message):
        self.lines.append(message)


def test_слой_селекторов_выигрывает():
    hit = resolve.resolve(ФейкCtx(found=ФейкЭлемент(), dump=ДАМП),
                          sel=[dict(text="Войти")], text=["Войти"], timeout=0.1)
    assert hit.layer == "selector"
    assert (hit.x, hit.y) == (0.5, 0.225)   # центр bounds, делённый на размер экрана


def test_текст_дерева_когда_селекторы_мимо():
    hit = resolve.resolve(ФейкCtx(dump=ДАМП), sel=[dict(resourceId="нет")],
                          text=["Войти"], timeout=0.1)
    assert hit.layer == "tree-text"
    assert abs(hit.x - 0.2) < 0.01 and abs(hit.y - 0.37) < 0.01


def test_ocr_когда_дерево_пустое(monkeypatch):
    from farm.vision import ocr
    monkeypatch.setattr(ocr, "backend", lambda: "vision")
    monkeypatch.setattr(ocr, "ocr", lambda b: [ocr.Box("Войти", 0.5, 0.6, 0.95)])
    hit = resolve.resolve(ФейкCtx(shot=b"png"), text=["Войти"], timeout=0.1)
    assert hit.layer == "ocr" and (hit.x, hit.y) == (0.5, 0.6)


def test_слой_шаблона(monkeypatch):
    from farm.vision import template
    monkeypatch.setattr(template, "available", lambda: True)
    monkeypatch.setattr(template, "find", lambda s, t, base_scale=1.0: (0.3, 0.7, 0.9))
    ctx = ФейкCtx(shot=b"png", asset=(b"crop", 1.0))
    hit = resolve.resolve(ctx, img="07_login.png", timeout=0.1)
    assert hit.layer == "template" and (hit.x, hit.y) == (0.3, 0.7)


def test_координата_за_границей_клэмпится():
    """OCR отдаёт бокс у самого края экрана: 1 - (y + h/2) даёт 1.004 или

    -0.002. to_pixels() считает долями только строго 0..1, промах в 0.004
    читает как целый пиксель и превращает тап в (0,0) — «Назад»/«Закрыть»
    на большинстве экранов. Клэмп в Hit должен поймать это на любом слое.
    """
    assert resolve.Hit(0.5, 1.004, "ocr", "край").y == 1.0
    assert resolve.Hit(0.5, -0.002, "ocr", "край").y == 0.0
    assert resolve.Hit(-0.001, 0.5, "point").x == 0.0
    assert resolve.Hit(1.5, 0.5, "template").x == 1.0


def test_шаблон_не_роняет_шаг_если_asset_кинул_ошибку(monkeypatch):
    """ctx.asset(img) раньше вызывался вне try — OSError при чтении кропа

    ронял шаг, хотя соседние _by_ocr/_by_tree_text честно глушат всё.
    """
    from farm.vision import template

    monkeypatch.setattr(template, "available", lambda: True)

    class ПадающийCtx(ФейкCtx):
        def asset(self, name):
            raise OSError("диск отвалился")

    hit = resolve.resolve(ПадающийCtx(shot=b"png"), img="07_login.png", timeout=0.1)
    assert hit is None


def test_координаты_последний_резерв():
    assert resolve.resolve(ФейкCtx(), at=(0.5, 0.9), timeout=0.1).layer == "point"


def test_цель_не_найдена_ничем():
    assert resolve.resolve(ФейкCtx(), sel=[dict(text="x")], timeout=0.1) is None


def test_пустая_цель_отвергается():
    with pytest.raises(ValueError):
        resolve.resolve(ФейкCtx(), timeout=0.1)
