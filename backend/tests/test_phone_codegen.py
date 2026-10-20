"""Код новых шагов и предупреждение о приложении вне библиотеки."""
from farm.recorder import codegen, steps
from farm.recorder.validate import validate

META = {"name": "Тест", "description": "", "watch_popups": False}


def body(*raw):
    text = codegen.render(META, {}, [steps.normalize_step(s) for s in raw])
    lines = text.splitlines()
    start = lines.index("def run(ctx):") + 1
    return [line[4:] for line in lines[start:] if line.strip()]


def test_блок_если_на_телефоне():
    assert body(
        {"kind": "if_phone", "args": {"span": 1, "check": "app_installed",
                                      "package": "com.vk.app", "negate": True}},
        {"kind": "sleep", "args": {"seconds": 1}},
    ) == ['if not ctx.phone_is("app_installed", package="com.vk.app"):', "    ctx.sleep(1)"]


def test_числа_и_платформа():
    assert body(
        {"kind": "if_phone", "args": {"span": 1, "check": "battery_below", "percent": 20}},
        {"kind": "finish", "args": {"result": "fail", "reason": "разряжен"}},
    )[0] == 'if ctx.phone_is("battery_below", percent=20):'
    assert body(
        {"kind": "if_phone", "args": {"span": 1, "check": "no_account", "platform": "vk"}},
        {"kind": "sleep", "args": {"seconds": 1}},
    )[0] == 'if ctx.phone_is("no_account", platform="vk"):'


def test_приложение_готово():
    assert body({"kind": "ensure_app", "args": {"package": "com.vk.app"}}) == \
        ['ctx.ensure_app("com.vk.app")']
    assert body({"kind": "ensure_app", "args": {"package": "com.vk.app", "min_version": "8.40",
                                               "install": False}}) == \
        ['ctx.ensure_app("com.vk.app", min_version="8.40", install=False)']
    assert body({"kind": "ensure_app", "args": {"package": "com.vk.app"}, "optional": True})[0] \
        .startswith("ctx.attempt(lambda: ctx.ensure_app(")


def test_предупреждение_нет_в_библиотеке():
    payload = {"meta": META, "params": {},
               "steps": [{"kind": "ensure_app", "args": {"package": "com.vk.app"}}]}
    out = validate(payload, library={"org.telegram.messenger"})
    assert out["ok"] is True
    assert any("нет в библиотеке" in w["text"] for w in out["warnings"])
    assert not validate(payload, library={"com.vk.app"})["warnings"]
    assert not validate(payload)["warnings"]


def test_карта_строк_с_блоком_телефона():
    raw = [{"kind": "if_phone", "args": {"span": 1, "check": "app_installed",
                                         "package": "com.vk.app"}},
           {"kind": "sleep", "args": {"seconds": 1}}]
    text, line_map = codegen.render_mapped(META, {}, [steps.normalize_step(s) for s in raw])
    lines = text.splitlines()
    i = next(n for n, line in enumerate(lines) if line.strip() == "ctx.sleep(1)")
    assert lines[i].startswith("        ")
    assert line_map[i + 1] == 1 and line_map[i] == 0
