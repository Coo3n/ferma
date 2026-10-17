"""Генерация исходника сценария из записанных шагов."""
from datetime import date

from farm.recorder import codegen, steps

DAY = date(2026, 7, 26)
META = {"name": "Тест", "description": "", "watch_popups": False}


def build(*raw):
    return [steps.normalize_step(item) for item in raw]


def body(text):
    """Строки тела run(ctx) без отступа — то, ради чего пишется тест."""
    lines = text.splitlines()
    start = lines.index("def run(ctx):") + 1
    return [line[4:] for line in lines[start:] if line.strip()]


def test_каждый_шаг_даёт_ожидаемую_строку():
    result = codegen.render(META, {}, build(
        {"kind": "click", "args": {},
         "selector": {"call": "click", "args": 'resourceId="a:id/b"'}},
        {"kind": "tap", "args": {"x": 0.5, "y": 0.25}},
        {"kind": "long_tap", "args": {"x": 0.5, "y": 0.25, "duration": 1.0}},
        {"kind": "swipe", "args": {"x1": 0.5, "y1": 0.75, "x2": 0.5, "y2": 0.3}},
        {"kind": "type", "args": {"value": "привет"}},
        {"kind": "type", "args": {"value": "привет", "clear": True}},
        {"kind": "key", "args": {"name": "back"}},
        {"kind": "unlock", "args": {}},
        {"kind": "launch_app", "args": {"package": "com.a"}},
        {"kind": "stop_app", "args": {"package": "com.a"}},
        {"kind": "open_url", "args": {"url": "https://a.b"}},
        {"kind": "shell", "args": {"cmd": "input keyevent 26"}},
        {"kind": "sleep", "args": {"seconds": 1.5}},
        {"kind": "screenshot", "args": {"name": "итог"}},
        {"kind": "screenshot", "args": {}},
    ), today=DAY)

    assert body(result) == [
        'ctx.click(resourceId="a:id/b")',
        "ctx.tap(0.5, 0.25)",
        "ctx.long_tap(0.5, 0.25, 1)",
        "ctx.swipe(0.5, 0.75, 0.5, 0.3, 0.25)",
        'ctx.type("привет")',
        'ctx.type("привет", clear=True)',
        'ctx.key("back")',
        "ctx.unlock()",
        'ctx.launch_app("com.a")',
        'ctx.stop_app("com.a")',
        'ctx.open_url("https://a.b")',
        'ctx.shell("input keyevent 26")',
        "ctx.sleep(1.5)",
        'ctx.screenshot("итог")',
        "ctx.screenshot()",
    ]


def test_запасные_селекторы_дают_click_any():
    result = codegen.render(META, {}, build(
        {"kind": "click", "args": {},
         "selector": {"call": "click", "args": 'resourceId="a:id/b"',
                      "fallbacks": ['text="Войти"', 'textContains="Вой"']}},
    ), today=DAY)
    assert ('ctx.click_any(dict(resourceId="a:id/b"), '
            'dict(text="Войти"), dict(textContains="Вой"))') in result


def test_галка_human_даёт_humanize():
    on = codegen.render({"name": "Т", "description": "", "watch_popups": False,
                         "human": True}, {},
                        build({"kind": "unlock", "args": {}}), today=DAY)
    assert "ctx.humanize()" in on
    assert "ctx.humanize()" not in codegen.render(META, {},
                                                  build({"kind": "unlock", "args": {}}),
                                                  today=DAY)


def test_метка_становится_комментарием():
    result = codegen.render(META, {}, build(
        {"kind": "key", "args": {"name": "back"}, "note": "Кнопка назад"},
    ), today=DAY)
    assert 'ctx.key("back")  # Кнопка назад' in result


def test_экранирование_кавычек_и_бэкслешей():
    assert codegen.literal('он сказал "да"') == '"он сказал \\"да\\""'
    assert codegen.literal("путь\\к") == '"путь\\\\к"'
    assert codegen.literal("две\nстроки") == '"две\\nстроки"'


def test_экранирование_в_названии_и_описании():
    result = codegen.render(
        {"name": 'Тест "боевой"', "description": "путь\\сюда", "watch_popups": False},
        {}, build({"kind": "unlock", "args": {}}), today=DAY)
    assert 'NAME = "Тест \\"боевой\\""' in result
    assert 'DESCRIPTION = "путь\\\\сюда"' in result


def test_параметр_заменяет_литерал_и_попадает_в_PARAMS():
    result = codegen.render(META, {"login": {"label": "Логин", "default": "user@a.b"}}, build(
        {"kind": "type", "args": {"value": "user@a.b"}, "param": "login"},
    ), today=DAY)
    assert 'ctx.type(ctx.params["login"])' in result
    assert '"login": {"label": "Логин", "default": "user@a.b"},' in result
    assert '"user@a.b")' not in result


def test_числовой_default_остаётся_числом():
    result = codegen.render(META, {"wait": {"label": "Пауза", "default": 2.5}}, build(
        {"kind": "sleep", "args": {"seconds": 2.5}, "param": "wait"},
    ), today=DAY)
    assert '"wait": {"label": "Пауза", "default": 2.5},' in result
    assert "ctx.sleep(ctx.params[\"wait\"])" in result


def test_без_параметров_блок_PARAMS_не_печатается():
    result = codegen.render(META, {}, build({"kind": "unlock", "args": {}}), today=DAY)
    assert "PARAMS" not in result


def test_watch_popups_управляется_галкой():
    on = codegen.render({"name": "Т", "description": "", "watch_popups": True}, {},
                        build({"kind": "unlock", "args": {}}), today=DAY)
    assert "ctx.watch_popups()" in on
    assert "ctx.watch_popups()" not in codegen.render(META, {},
                                                      build({"kind": "unlock", "args": {}}),
                                                      today=DAY)


def test_пустое_тело_получает_pass():
    result = codegen.render(META, {}, [], today=DAY)
    assert body(result) == ["pass"]


def test_шапка_файла():
    result = codegen.render(META, {}, build({"kind": "unlock", "args": {}}), today=DAY)
    assert result.startswith('"""Записано конструктором фермы 26.07.2026."""\n')
    assert "RECORDED = True" in result
    assert result.endswith("\n")


def test_сгенерированный_файл_импортируется_фермой(tmp_path, monkeypatch):
    """Главная проверка: ферма обязана принять то, что сгенерировал конструктор."""
    from farm import config, scenarios

    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()

    source = codegen.render(
        {"name": 'Логин "боевой"', "description": "путь\\сюда",
         "watch_popups": True, "human": True},
        {"login": {"label": "Логин", "default": "user@a.b"},
         "wait": {"label": "Пауза", "default": 2.5}},
        build(
            {"kind": "launch_app", "args": {"package": "com.a"}},
            {"kind": "click", "args": {},
             "selector": {"call": "click", "args": 'resourceId="com.a:id/email"',
                          "fallbacks": ['textContains="Почта"']},
             "note": "Поле «Почта»"},
            {"kind": "type", "args": {"value": "user@a.b"}, "param": "login"},
            {"kind": "sleep", "args": {"seconds": 2.5}, "param": "wait"},
            {"kind": "screenshot", "args": {"name": "итог"}},
        ),
        today=DAY,
    )
    (tmp_path / "logins.py").write_text(source, "utf-8")

    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["logins"].error == ""
    assert found["logins"].recorded is True
    assert found["logins"].name == 'Логин "боевой"'
    assert found["logins"].params["login"]["default"] == "user@a.b"
    assert found["logins"].to_dict()["recorded"] is True


def test_обычный_сценарий_не_помечен_записанным(tmp_path, monkeypatch):
    from farm import config, scenarios

    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    (tmp_path / "ручной.py").write_text("def run(ctx):\n    pass\n", "utf-8")

    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["ручной"].recorded is False


def test_click_со_слоями_рендерит_click_target():
    text = codegen.render(META, {}, build({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Войти"',
                     "fallbacks": ['description="Войти"']},
        "texts": ["Войти", "Log in"],
        "crop": "07_login.png",
        "point": [0.52, 0.81],
    }), DAY)
    assert body(text) == [
        'ctx.click_target(sel=[dict(text="Войти"), dict(description="Войти")], '
        'text=["Войти", "Log in"], img="07_login.png", at=(0.52, 0.81))'
    ]


def test_click_без_слоёв_рендерится_как_прежде():
    text = codegen.render(META, {}, build({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Ок"'},
    }), DAY)
    assert body(text) == ['ctx.click(text="Ок")']


def test_expect_рендерит_expect_screen():
    text = codegen.render(META, {}, build({
        "kind": "expect",
        "args": {"name": "login"},
        "any": ['resourceId="com.app:id/title"', 'text="Вход"'],
    }), DAY)
    assert body(text) == [
        'ctx.expect_screen("login", '
        'any=[dict(resourceId="com.app:id/title"), dict(text="Вход")])'
    ]


def test_сломанный_записанный_файл_остаётся_помеченным(tmp_path, monkeypatch):
    """Иначе битый файл нельзя было бы удалить из интерфейса."""
    from farm import config, scenarios

    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    scenarios._cache.clear()
    (tmp_path / "битый.py").write_text(
        'RECORDED = True\nNAME = "Битый"\nдef run(ctx):\n', "utf-8")

    found = {s.key: s for s in scenarios.discover(force=True)}
    assert found["битый"].error != ""
    assert found["битый"].recorded is True


def test_имя_экрана_с_кавычками_не_ломает_файл():
    """Имя якоря человек правит руками в интерфейсе — там может оказаться что угодно.

    Кавычка внутри имени не должна разваливать сгенерированный файл, поэтому
    проверяем не подстроку, а то, что результат вообще компилируется.
    """
    text = codegen.render(META, {}, build({
        "kind": "expect",
        "args": {"name": 'вход "в" аккаунт'},
        "any": ['text="Вход"'],
    }), DAY)
    assert r'ctx.expect_screen("вход \"в\" аккаунт"' in body(text)[0]
    compile(text, "<scenario>", "exec")
