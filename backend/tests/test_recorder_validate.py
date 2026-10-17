"""Проверка сценария до запуска."""
from farm.recorder.validate import validate

META = {"name": "Т"}


def _sel(args='text="Ок"', fallbacks=()):
    return {"call": "click", "args": args, "fallbacks": list(fallbacks)}


def run(steps, **kw):
    return validate({"meta": META, "params": kw.pop("params", {}), "steps": steps}, **kw)


def texts(res, key="errors"):
    return [(e["step"], e["text"]) for e in res[key]]


def test_чистый_сценарий_ок():
    r = run([{"kind": "key", "args": {"name": "back"}}])
    assert r["ok"] and not r["errors"] and not r["warnings"]


def test_ошибки_собираются_списком_с_индексами():
    r = run([{"kind": "tap", "args": {"x": 1}}, {"kind": "key", "args": {"name": "b"}},
             {"kind": "nope"}])
    assert not r["ok"]
    assert [e["step"] for e in r["errors"]] == [0, 2]


def test_пустой_сценарий_и_плохое_имя():
    assert texts(run([]), "warnings") == [(-1, "в сценарии нет шагов")]
    r = validate({"meta": {"name": ""}, "steps": []})
    assert not r["ok"] and r["errors"][0]["step"] == -1


def test_параметр_не_описан():
    r = run([{"kind": "type", "args": {"value": "a"}, "param": "login"}])
    assert not r["ok"] and "login" in r["errors"][0]["text"]
    assert run([{"kind": "type", "args": {"value": "a"}, "param": "login"}],
               params={"login": {"label": "L", "default": ""}})["ok"]


def test_блок_ветки_должен_существовать():
    arms = [{"name": "а", "any": ['text="Х"'], "run": "gone"},
            {"name": "б", "any": ['text="У"'], "run": "ok_blk"},
            {"name": "в", "any": ['text="Я"'], "run": "broken"}]
    r = run([{"kind": "branch", "args": {"name": "в"}, "arms": arms}],
            blocks={"ok_blk": True, "broken": False})
    assert [e["step"] for e in r["errors"]] == [0, 0]
    assert "gone" in r["errors"][0]["text"] and "broken" in r["errors"][1]["text"]


def test_кроп_и_пакет_и_длинная_пауза():
    click = {"kind": "click", "args": {}, "selector": _sel(), "crop": "01_click.png"}
    r = run([click, {"kind": "launch_app", "args": {"package": "com.x"}},
             {"kind": "sleep", "args": {"seconds": 300}}],
            assets=set(), packages={"com.y"})
    assert texts(r) == [(0, "кроп «01_click.png» не приложен — слой поиска по картинке не сработает")]
    assert [w["step"] for w in r["warnings"]] == [1, 2]


def test_голый_клик_и_необязательный_последний():
    r = run([{"kind": "click", "args": {}, "selector": _sel()},
             {"kind": "key", "args": {"name": "b"}, "optional": True}])
    assert [w["step"] for w in r["warnings"]] == [0, 1]
    ok = run([{"kind": "click", "args": {}, "selector": _sel(fallbacks=['text="Да"'])}])
    assert not ok["warnings"]
