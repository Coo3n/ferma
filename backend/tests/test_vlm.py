"""Нейросеть-помощник: разбор ответа, пороги, запреты, лимиты, обучение, подсказка.

Сеть не нужна: клиент модели подменяется (`client.ask`), экран — фейковый ctx.
"""
import threading

import pytest

from farm import config, deviations as dv, resolve
from farm.vlm import advise, client, learn, locate, safety, settings, usage
from farm.vlm.parse import parse

XML = ('<hierarchy><node bounds="[0,0][1000,2000]" class="android.widget.FrameLayout" '
       'package="com.app" clickable="false">'
       '<node bounds="[400,1000][600,1100]" resource-id="com.app:id/go" text="Далее" '
       'class="android.widget.Button" clickable="true"/>'
       '<node bounds="[400,1400][600,1500]" resource-id="com.app:id/pay" text="Оплатить" '
       'class="android.widget.Button" clickable="true"/>'
       '</node></hierarchy>')


class Ctx:
    serial = "S1"
    size = (1000, 2000)
    job_id = "job1"
    scenario_key = "sc"
    scenario_name = "Сц"
    device_name = "Ph"

    def __init__(self, xml=XML):
        self.xml = xml
        self.logs = []

    def log(self, m):
        self.logs.append(m)

    def check_cancel(self):
        pass

    def dump_hierarchy(self):
        return self.xml

    def screen_bytes(self):
        return b"frame"

    def find(self, timeout=1.0, **s):
        return None


@pytest.fixture(autouse=True)
def изоляция(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VLM_FILE", tmp_path / "vlm.json")
    monkeypatch.setattr(config, "VLM_USAGE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(config, "VLM_LEARNED_FILE", tmp_path / "learned.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for var in list(__import__("os").environ):
        if var.startswith("FARM_VLM"):
            monkeypatch.delenv(var)
    monkeypatch.setattr(locate.control, "is_secure", lambda serial: False)
    monkeypatch.setattr(locate.control, "is_blank", lambda b: False)
    monkeypatch.setattr(locate, "_ocr_items", lambda image: [])
    usage.reset_jobs()
    dv.deviations.clear()
    yield


def включить(**kw):
    settings.save({"enabled": True, "url": "http://x/v1", "model": "m", **kw})


def модель(monkeypatch, reply):
    calls = []

    def ask(image, prompt, cfg=None):
        calls.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(client, "ask", ask)
    return calls


GO = '{"x": 500, "y": 525, "confidence": 0.9, "why": "кнопка"}'   # центр «Далее»
WHAT = {"text": ["Продолжить"], "sel": [], "key": "k1"}


# ------------------------------------------------------------------ разбор

def test_разбор_хорошего_и_с_мусором():
    a = parse('Вот ответ:\n```json\n' + GO + '\n``` готово')
    assert (a.x, a.y, a.confidence) == (0.5, 0.525, 0.9)


@pytest.mark.parametrize("bad", [
    "", "ничего", "{", '{"x": 1}', '{"x": 1, "y": 2}',
    '{"x": 1001, "y": 5, "confidence": 0.9}', '{"x": -1, "y": 5, "confidence": 0.9}',
    '{"x": 5, "y": 5, "confidence": 1.5}', '{"x": "5", "y": 5, "confidence": 0.9}',
    '{"x": true, "y": 5, "confidence": 0.9}',
    '{"found": false, "why": "нет"}',
])
def test_разбор_отвергает(bad):
    assert parse(bad) is None


# ------------------------------------------------------------------ выключено

def test_по_умолчанию_клиент_не_вызывается(monkeypatch):
    calls = модель(monkeypatch, GO)
    assert locate.locate(Ctx(), WHAT) is None
    assert calls == []


def test_окружение_важнее_файла(monkeypatch):
    включить()
    monkeypatch.setenv("FARM_VLM", "0")
    assert not settings.enabled()


# ------------------------------------------------------------------ слой

def test_успех_даёт_hit_и_журнал(monkeypatch):
    включить()
    модель(monkeypatch, GO)
    ctx = Ctx()
    hit = locate.locate(ctx, WHAT)
    assert hit.layer == "vlm" and (hit.x, hit.y) == (0.5, 0.525)
    assert any("нейросеть подсказала" in m and "0.90" in m for m in ctx.logs)


def test_порог_уверенности(monkeypatch):
    включить()
    модель(monkeypatch, '{"x": 500, "y": 525, "confidence": 0.3}')
    assert locate.locate(Ctx(), WHAT) is None


def test_found_false(monkeypatch):
    включить()
    модель(monkeypatch, '{"found": false, "why": "нет"}')
    assert locate.locate(Ctx(), WHAT) is None


def test_ошибка_клиента_не_роняет(monkeypatch):
    включить()
    модель(monkeypatch, client.VlmError("недоступна"))
    assert locate.locate(Ctx(), WHAT) is None


# ------------------------------------------------------------------ запреты

@pytest.mark.parametrize("goal", ["Оплатить", "Купить", "Delete account", "Выйти",
                                  "Отправить", "Подписаться", "Log out", "Вoйти и оплатить"])
def test_запрет_по_цели(monkeypatch, goal):
    включить()
    calls = модель(monkeypatch, GO)
    assert locate.locate(Ctx(), {"text": [goal], "key": "k"}) is None
    assert calls == []
    assert dv.deviations.list()[0]["kind"] == dv.VLM_DENIED


def test_запрет_по_тексту_в_точке(monkeypatch):
    включить()
    модель(monkeypatch, '{"x": 500, "y": 725, "confidence": 0.95}')   # центр «Оплатить»
    assert locate.locate(Ctx(), {"text": ["Далее"], "key": "k"}) is None
    assert dv.deviations.list()[0]["kind"] == dv.VLM_DENIED


def test_безобидное_не_запрещено():
    assert safety.irreversible("Далее", "Продолжить", "Войти") == ""
    assert safety.irreversible("Выйти") == "выход из аккаунта"


def test_пароль_не_отправляется(monkeypatch):
    включить()
    calls = модель(monkeypatch, GO)
    xml = XML.replace('clickable="true"/>', 'clickable="true" password="true"/>', 1)
    assert locate.locate(Ctx(xml), WHAT) is None
    assert locate.locate(Ctx(), {"text": ["Введите пароль"]}) is None
    assert calls == []


def test_защищённый_экран(monkeypatch):
    включить()
    calls = модель(monkeypatch, GO)
    monkeypatch.setattr(locate.control, "is_secure", lambda s: True)
    assert locate.locate(Ctx(), WHAT) is None
    assert calls == []


# ------------------------------------------------------------------ лимиты

def test_лимит_на_задачу(monkeypatch):
    включить(max_per_job=2)
    calls = модель(monkeypatch, '{"found": false}')
    for _ in range(5):
        locate.locate(Ctx(), WHAT)
    assert len(calls) == 2


def test_лимит_на_сутки_в_потоках(monkeypatch):
    включить(max_per_job=100, max_per_day=7)
    calls = модель(monkeypatch, '{"found": false}')

    def work(i):
        c = Ctx()
        c.job_id = f"j{i}"
        for _ in range(5):
            locate.locate(c, WHAT)
    ths = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert len(calls) == 7 and usage.used_today() == 7


# ------------------------------------------------------------------ обучение

def test_обучение_патч_и_память(monkeypatch):
    включить()
    модель(monkeypatch, GO)
    ctx = Ctx()
    hit = locate.locate(ctx, WHAT)
    assert hit and ctx.vlm_patch == {"sel": [{"resourceId": "com.app:id/go"}]}
    assert learn.lookup("k1") == [{"resourceId": "com.app:id/go"}]
    kinds = [d["kind"] for d in dv.deviations.list()]
    assert dv.VLM_ASSIST in kinds


def test_без_узла_только_факт(monkeypatch):
    включить()
    модель(monkeypatch, GO)
    ctx = Ctx('<hierarchy></hierarchy>')
    # дерева нет, но OCR прочёл безобидную надпись под точкой
    monkeypatch.setattr(locate, "_ocr_items", lambda image: [("Далее", 0.5, 0.5)])
    assert locate.locate(ctx, WHAT).layer == "vlm"
    assert not hasattr(ctx, "vlm_patch") and learn.lookup("k1") == []


def test_следующий_телефон_находит_селектором_без_вызова(monkeypatch):
    включить()
    calls = модель(monkeypatch, GO)
    first = Ctx()
    k = learn.key(first, None, ["Продолжить"], None, None)
    locate.locate(first, {**WHAT, "key": k})
    assert len(calls) == 1

    class El:
        info = {"bounds": {"left": 400, "right": 600, "top": 1000, "bottom": 1100}}
    second = Ctx()
    second.find = lambda timeout=1.0, **s: El() if s == {"resourceId": "com.app:id/go"} else None
    hit = resolve.resolve(second, text=["Продолжить"], timeout=0.1)
    assert hit.layer == "selector" and len(calls) == 1


def test_resolve_зовёт_vlm_перед_точкой(monkeypatch):
    включить()
    модель(monkeypatch, GO)
    hit = resolve.resolve(Ctx(), text=["Продолжить"], at=(0.1, 0.1), timeout=0.1)
    assert hit.layer == "vlm"


def test_resolve_без_vlm_точка(monkeypatch):
    calls = модель(monkeypatch, GO)
    hit = resolve.resolve(Ctx(), text=["Продолжить"], at=(0.1, 0.1), timeout=0.1)
    assert hit.layer == "point" and calls == []


# ------------------------------------------------------------------ подсказка

def test_advise_ответ(monkeypatch):
    включить()
    monkeypatch.setattr(advise.control, "screenshot", lambda s, quality=85: b"img")
    модель(monkeypatch, "  Открыт диалог.\n Закройте его. ")
    assert advise.advise("S1", "нажать «Далее»", "j") == "Открыт диалог. Закройте его."


def test_advise_не_роняет(monkeypatch):
    включить()
    monkeypatch.setattr(advise.control, "screenshot", lambda s, quality=85: b"img")
    модель(monkeypatch, RuntimeError("упало"))
    assert advise.advise("S1", "x", "j") == ""
    monkeypatch.setattr(advise.control, "screenshot",
                        lambda s, quality=85: (_ for _ in ()).throw(OSError("нет кадра")))
    assert advise.advise("S1", "x", "j") == ""


def test_advise_выключено(monkeypatch):
    calls = модель(monkeypatch, "текст")
    assert advise.advise("S1", "x", "j") == ""
    assert calls == []


# ------------------------------------------------------------------ API

def test_api_маскирует_ключ():
    from farm.api import vlm as api
    api.put_settings({"enabled": True, "url": "http://h/v1", "key": "SECRET"})
    out = api.get_settings()
    assert out["key"] != "SECRET" and out["key"]
    api.put_settings({"key": out["key"], "model": "m2"})   # маска не затирает ключ
    assert settings.get().key == "SECRET" and settings.get().model == "m2"


def test_api_адрес_только_http():
    from fastapi import HTTPException
    from farm.api import vlm as api
    with pytest.raises(HTTPException):
        api.put_settings({"url": "file:///etc/passwd"})


def test_сетевая_ошибка_не_списывает_квоту(monkeypatch):
    from farm.vlm import client, locate, usage

    class Ctx:
        serial = "S"
        job_id = "jref"
        logs: list = []
        size = (360, 640)

        def log(self, m):
            self.logs.append(m)

        def screen_bytes(self):
            import io
            from PIL import Image
            b = io.BytesIO()
            Image.new("RGB", (40, 40), (10, 120, 200)).save(b, "PNG")
            return b.getvalue()

        def dump_hierarchy(self):
            raise RuntimeError("нет дерева")

    monkeypatch.setattr(locate.settings, "get", lambda: type("C", (), dict(
        enabled=True, url="http://x", max_per_job=3, max_per_day=10, min_confidence=0.6))())

    def boom(*a, **k):
        raise client.VlmError("нейросеть недоступна")
    monkeypatch.setattr(client, "ask", boom)
    usage.reset_jobs()
    before = usage.used_today()
    assert locate.locate(Ctx(), {"text": ["Далее"]}) is None
    assert usage.used_today() == before
    assert locate.usage.reserve("jref", 1, 10)[0]   # лимит на задачу не съеден
