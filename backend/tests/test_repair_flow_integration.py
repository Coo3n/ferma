"""Сквозная цепочка: запись сценария → падение/остановка → снимок и дамп → починка шага.

Устройства нет: подменяем только границу с ним (control, resolve, tap/sleep
контекста). Всё остальное настоящее: save/codegen/scenarios, _execute,
_record_failure/_hold, Runner.decide, маршруты API.
"""
import base64
import io
import os
import json
import threading
import time
import types

import pytest
from fastapi import HTTPException
from PIL import Image

from farm import config, control, resolve, scenarios, deviations as dv
from farm.api import deviations as api_dev
from farm.api import jobs as api_jobs
from farm.context import DeviceContext, normalize_target
from farm.devices import runner as R
from farm.recorder import save, steps

XML = ('<?xml version="1.0"?><hierarchy rotation="0">'
       '<node index="0" text="ОК" resource-id="a:id/ok" class="android.widget.Button" '
       'package="a" content-desc="" clickable="true" enabled="true" '
       'bounds="[100,200][300,400]"/></hierarchy>')
SIZE = (1080, 2400)
META = {"name": "Вход", "description": "", "watch_popups": False}
KEY = "flow_login"

OLD_SEL = [{"text": "Войти"}]
OLD_TEXT = ["Войти", "Log in"]
OLD_AT = [0.52, 0.81]
OLD_TARGET = {"sel": OLD_SEL, "text": OLD_TEXT, "img": "", "at": OLD_AT}


def _jpeg() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (8, 16), (10, 120, 200)).save(b, "JPEG")
    return b.getvalue()


JPEG = _jpeg()


def _click(sel_args, texts, point):
    return steps.normalize_step({
        "kind": "click", "selector": {"call": "click", "args": sel_args},
        "texts": texts, "point": point})


def _recipe_steps(click=None):
    """0 sleep, 1 tap, 2 click_target, 3 expect, 4 tap."""
    return [
        steps.normalize_step({"kind": "sleep", "args": {"seconds": 1}}),
        steps.normalize_step({"kind": "tap", "args": {"x": 10, "y": 20}}),
        click or _click('text="Войти"', OLD_TEXT, OLD_AT),
        steps.normalize_step({"kind": "expect", "args": {"name": "home"},
                              "any": ['text="Дом"']}),
        steps.normalize_step({"kind": "tap", "args": {"x": 1, "y": 2}}),
    ]


@pytest.fixture(autouse=True)
def мир(tmp_path, monkeypatch):
    """Изолированные каталоги, кэш сценариев и отклонения; устройство подменено."""
    sc_dir, art = tmp_path / "scenarios", tmp_path / "art"
    sc_dir.mkdir()
    monkeypatch.setattr(config, "SCENARIOS_DIR", sc_dir)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", art)
    monkeypatch.setattr(config, "HOLD", False)
    monkeypatch.setattr(scenarios, "_cache", {})
    dv.deviations.clear()

    def shot(serial, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)

    monkeypatch.setattr(control, "save_screenshot", shot)
    monkeypatch.setattr(control, "dump_hierarchy", lambda s: XML)
    monkeypatch.setattr(control, "size", lambda s: SIZE)
    monkeypatch.setattr(control, "clear_logcat", lambda s: None)
    monkeypatch.setattr(control, "logcat_tail", lambda s, n: "")
    monkeypatch.setattr(control, "current_app", lambda s: "a")
    monkeypatch.setattr(R.registry, "acquire", lambda s, j: True)
    monkeypatch.setattr(R.registry, "release", lambda s, j: None)
    for name, fn in (("_settle", lambda self: None), ("_rescue", lambda self: False),
                     ("tap", lambda self, x, y: None), ("sleep", lambda self, s: None),
                     ("_expect_artifacts", lambda self, n: None)):
        monkeypatch.setattr(DeviceContext, name, fn)
    yield art
    dv.deviations.clear()
    scenarios._cache.clear()


def _resolver(monkeypatch, hit_if=None):
    """resolve.resolve: None (промах) или попадание, когда hit_if(kw) истинно."""
    calls = []

    def fake(ctx, **kw):
        calls.append(kw)
        if hit_if and hit_if(kw):
            return types.SimpleNamespace(layer="selector", detail="", x=1, y=2)
        return None

    monkeypatch.setattr(resolve, "resolve", fake)
    return calls


def _job(jid):
    return R.Job(id=jid, scenario_key=KEY, scenario_name="Вход",
                 serial="s", device_name="Пикси", params={})


def _run(job):
    R.runner.jobs[job.id] = job
    try:
        R._execute(job)
    finally:
        R.runner.jobs.pop(job.id, None)
    return job


def _devs(kind=dv.FAIL):
    return [d for d in dv.deviations.list() if d["kind"] == kind]


def _fail_deviation():
    (d,) = _devs(dv.FAIL)
    return d


def _record(monkeypatch=None):
    save.save(KEY, META, {}, _recipe_steps())


# ------------------------------------------------------------------- A

def test_A_падение_click_target_до_снимка_и_дампа(monkeypatch, мир):
    # звено: save(line_map) → _execute → step_index/miss → _record_failure → /shot, /dump
    _record()
    code = save.target_path(KEY).read_text("utf-8")
    assert "ctx.click_target(" in code and code.count("ctx.click_target(") == 1
    _resolver(monkeypatch)
    j = _run(_job("ja"))
    assert j.status == R.FAILED
    d = _fail_deviation()
    assert d["step_index"] == 2 and d["shot"] == "99_failure.jpg"
    assert json.loads(d["miss"]) == OLD_TARGET
    art = мир / "ja"
    for n in ("99_failure.jpg", "failure_hierarchy.xml", "failure_size.json"):
        assert (art / n).is_file(), n
    assert json.loads((art / "failure_size.json").read_text()) == \
        {"width": 1080, "height": 2400}

    s = api_dev.deviation_shot(d["id"])
    assert s["url"] == "/api/jobs/ja/artifacts/99_failure.jpg"
    assert s["miss"] == OLD_TARGET and s["step_index"] == 2
    assert s["job_id"] == "ja" and s["kind"] == dv.FAIL

    dump = api_dev.deviation_dump(d["id"])
    assert (dump["width"], dump["height"]) == SIZE
    prefix = "data:image/jpeg;base64,"
    assert dump["screenshot"].startswith(prefix)
    assert base64.b64decode(dump["screenshot"][len(prefix):]) == JPEG
    assert dump["nodes"]


# ------------------------------------------------------------------- B

def test_B_падение_не_click_шага_без_чужого_miss(monkeypatch):
    # звено: индекс из трейсбэка, miss не тянется от прошлого успешного клика
    _record()
    _resolver(monkeypatch, hit_if=lambda kw: True)   # клик (шаг 2) проходит
    monkeypatch.setattr(DeviceContext, "_wait_features", lambda self, f, t: False)
    monkeypatch.setattr(DeviceContext, "escape", lambda self, chk: False)
    monkeypatch.setattr(DeviceContext, "_screen_texts", lambda self: [])
    j = _run(_job("jb"))
    assert j.status == R.FAILED and "ожидал экран" in j.error
    d = _fail_deviation()
    assert d["step_index"] == 3 and d["miss"] == ""
    assert d["shot"] == "99_failure.jpg"


# ------------------------------------------------------------------- C

def test_C_рукописный_сценарий_без_рецепта(monkeypatch):
    # звено: нет recipe.json → step_index -1, но снимок и дамп работают
    (config.SCENARIOS_DIR / "hand.py").write_text(
        "NAME = 'Рука'\n\ndef run(ctx):\n    ctx.fail('нет кнопки')\n", "utf-8")
    assert save.load_line_map("hand") == {}
    j = R.Job(id="jc", scenario_key="hand", scenario_name="Рука",
              serial="s", device_name="Пикси", params={})
    _run(j)
    assert j.status == R.FAILED
    d = _fail_deviation()
    assert d["step_index"] == -1 and d["shot"] == "99_failure.jpg" and d["miss"] == ""
    s = api_dev.deviation_shot(d["id"])
    assert s["step_index"] == -1 and s["miss"] == {}
    assert api_dev.deviation_dump(d["id"])["nodes"]


# ------------------------------------------------------------------- D

def _line_of(code, needle):
    (n,) = [i for i, l in enumerate(code.splitlines(), 1) if needle in l]
    return n


def test_D_починка_шага_и_повторный_прогон(monkeypatch):
    # звено: recipe → замена steps[step_index] → save(overwrite) → line_map → прогон
    _record()
    path = save.target_path(KEY)
    old_code = path.read_text("utf-8")
    old_map = save.load_line_map(KEY)
    old_stat = path.stat()
    _resolver(monkeypatch)
    _run(_job("jd1"))
    idx = _fail_deviation()["step_index"]
    assert idx == 2

    recipe = save.load_recipe(KEY)
    old_steps = recipe["steps"]
    new = _click('resourceId="a:id/enter"', ["Вход"], [0.3, 0.4])
    fixed = list(old_steps)
    fixed[idx] = new
    save.save(KEY, recipe["meta"], recipe["params"], fixed, overwrite=True,
              screen_width=recipe["screen_width"])

    code = path.read_text("utf-8")
    assert 'resourceId="a:id/enter"' in code and "at=(0.3, 0.4)" in code
    assert 'text="Войти"' not in code and "Log in" not in code
    lmap = save.load_line_map(KEY)
    assert lmap[_line_of(code, "a:id/enter")] == 2
    # остальные строки-шаги: то же соответствие строка → шаг, что и до правки
    assert sorted(lmap.values()) == sorted(old_map.values())
    assert {i: lmap[_line_of(code, t)] for i, t in ((0, "ctx.sleep"), (1, "ctx.tap(10"),
            (3, "expect_screen"), (4, "ctx.tap(1, 2)"))} == {0: 0, 1: 1, 3: 3, 4: 4}
    on_disk = save.load_recipe(KEY)["steps"]
    diff = [i for i, (a, b) in enumerate(zip(old_steps, on_disk)) if a != b]
    assert diff == [2] and len(on_disk) == len(old_steps)
    assert old_code != code

    # новый сценарий действительно идёт: резолвер знает только новый селектор
    monkeypatch.setattr(DeviceContext, "_wait_features", lambda self, f, t: True)
    calls = _resolver(monkeypatch, hit_if=lambda kw: kw["sel"] == [{"resourceId": "a:id/enter"}])
    # грубая ФС / запись в тот же тик: штамп файла как до правки — починка
    # не должна зависеть от времени, иначе прогон возьмёт старый модуль
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    j = _run(_job("jd2"))
    assert j.status == R.PASSED, j.lines
    assert calls[0]["text"] == ["Вход"] and calls[0]["at"] == (0.3, 0.4)


# ------------------------------------------------------------------- E, F

@pytest.fixture
def hold(monkeypatch):
    monkeypatch.setattr(config, "HOLD", True)
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 5.0)
    _record()


def _ждать_HELD(job, конец):
    while time.time() < конец and job.status != R.HELD:
        time.sleep(0.01)
    return job.status == R.HELD


def _в_потоке(job, действие):
    """Поток «человека»; ошибки его assert-ов возвращаются в основной поток."""
    ошибки, итог = [], []

    def тело():
        try:
            конец = time.time() + 4
            assert _ждать_HELD(job, конец), "задача не встала в HELD"
            итог.append(действие())
        except BaseException as e:  # noqa: BLE001
            ошибки.append(e)
            job._decided.set()          # не держим _execute до HOLD_TIMEOUT
            job.decision = job.decision or "drop"

    t = threading.Thread(target=тело, daemon=True)
    t.start()
    return t, ошибки, итог


def _строка(job, needle):
    return next(i for i, l in enumerate(job.lines) if needle in l)


def test_E_hold_решение_с_исправленной_целью(monkeypatch, hold, мир):
    # звено: _hold → deviation HOLD → decide(target) → click_target с патчем → PASSED
    NEW = {"sel": [{"resourceId": "a:id/enter"}], "text": ["Вход"], "at": [0.3, 0.4]}
    monkeypatch.setattr(DeviceContext, "_wait_features", lambda self, f, t: True)
    calls = _resolver(monkeypatch, hit_if=lambda kw: kw["sel"] == NEW["sel"])
    j = _job("je")
    R.runner.jobs[j.id] = j

    def человек():
        (d,) = _devs(dv.HOLD)
        assert d["step_index"] == 2 and json.loads(d["miss"]) == OLD_TARGET
        assert d["shot"].startswith("hold_") and (мир / "je" / d["shot"]).is_file()
        # цель как из UI: ключи sel/text/at, без img
        target = {"sel": NEW["sel"], "text": NEW["text"], "at": NEW["at"]}
        assert normalize_target(target) == target and "img" not in target
        return R.runner.decide(j.id, "retry", target)

    t, ошибки, итог = _в_потоке(j, человек)
    try:
        R._execute(j)
    finally:
        t.join(timeout=6)
        R.runner.jobs.pop(j.id, None)
    assert not t.is_alive() and not ошибки, ошибки
    assert итог == [True] and j.status == R.PASSED, j.lines
    assert len(calls) == 2 and calls[0]["sel"] == OLD_SEL
    assert calls[1]["sel"] == NEW["sel"] and calls[1]["text"] == ["Вход"]
    assert calls[1]["at"] == [0.3, 0.4]
    assert _строка(j, "жду решения") < _строка(j, "человек решил")


def test_F_hold_отрицательные_пути(monkeypatch, hold):
    # звено: валидация цели в decide/decide_job; задача остаётся HELD; двойной ответ
    _resolver(monkeypatch)
    j = _job("jf")
    R.runner.jobs[j.id] = j

    def человек():
        рез = {}
        with pytest.raises(ValueError):
            R.runner.decide(j.id, "retry", {"img": "../x.png"})
        for body in ({"decision": "retry", "target": {"at": [9, 9]}},
                     {"decision": "skip", "target": {"at": [0.1, 0.2]}}):
            with pytest.raises(HTTPException) as e:
                api_jobs.decide_job(j.id, body)
            assert e.value.status_code == 400
        assert j.status == R.HELD and not j._decided.is_set() and j.target_patch is None
        рез["drop"] = R.runner.decide(j.id, "drop")
        рез["again"] = R.runner.decide(j.id, "retry")
        with pytest.raises(HTTPException) as e:
            api_jobs.decide_job(j.id, {"decision": "retry",
                                       "target": {"at": [0.1, 0.2]}})
        assert e.value.status_code == 409
        return рез

    t, ошибки, итог = _в_потоке(j, человек)
    try:
        R._execute(j)
    finally:
        t.join(timeout=6)
        R.runner.jobs.pop(j.id, None)
    assert not t.is_alive() and not ошибки, ошибки
    assert итог == [{"drop": True, "again": False}]
    assert j.status == R.FAILED     # drop → падаем как раньше


# ------------------------------------------------------------------- G

def test_G_старый_артефакт_без_размера(monkeypatch, мир):
    # звено: нет failure_size.json → /dump 404 про размер экрана, /shot жив
    _record()
    _resolver(monkeypatch)
    _run(_job("jg"))
    (мир / "jg" / "failure_size.json").unlink()
    d = _fail_deviation()
    assert api_dev.deviation_shot(d["id"])["step_index"] == 2
    with pytest.raises(HTTPException) as e:
        api_dev.deviation_dump(d["id"])
    assert e.value.status_code == 404 and "размер экрана" in e.value.detail


# ------------------------------------------------------------------- прогресс по шагам

def test_прогресс_хронология_и_отчёт(monkeypatch, мир):
    _record()
    _resolver(monkeypatch, hit_if=lambda kw: True)
    monkeypatch.setattr(DeviceContext, "_wait_features", lambda self, f, t: True)
    j = _run(_job("jp"))
    assert j.status == R.PASSED
    assert j.step_total == 5 and j.step_index == 4
    assert [t["i"] for t in j.timeline] == [0, 1, 2, 3, 4]
    assert all(t["status"] == "ok" and "secs" in t for t in j.timeline)
    report = json.loads((мир / "jp" / "report.json").read_text("utf-8"))
    assert report["status"] == R.PASSED and len(report["steps"]) == 5
    assert "t0" not in report["steps"][0]
    d = j.to_dict(with_log=True)
    assert d["step_total"] == 5 and d["timeline"][0]["label"]


def test_падение_помечает_шаг_и_объясняет(monkeypatch, мир):
    _record()
    _resolver(monkeypatch)
    j = _run(_job("jf"))
    assert j.status == R.FAILED
    assert j.timeline[-1]["i"] == 2 and j.timeline[-1]["status"] == "failed"
    info = j.to_dict()["error_info"]
    assert info["kind"] == "not_found"
    report = json.loads((мир / "jf" / "report.json").read_text("utf-8"))
    assert report["steps"][-1]["status"] == "failed"


def test_запуск_с_шага_пропускает_предыдущие(monkeypatch, мир):
    _record()
    _resolver(monkeypatch, hit_if=lambda kw: True)
    monkeypatch.setattr(DeviceContext, "_wait_features", lambda self, f, t: True)
    j = _job("js")
    j.start_step = 3
    _run(j)
    assert j.status == R.PASSED
    assert [t["i"] for t in j.timeline] == [3, 4]
    assert any("запуск с шага 4" in line for line in j.lines)


def test_submit_отвергает_плохой_start_step_и_speed(monkeypatch):
    _record()
    monkeypatch.setattr(R.registry, "get", lambda s: types.SimpleNamespace(name="П"))
    with pytest.raises(ValueError, match="нет шага"):
        R.runner.submit(KEY, ["s"], start_step=9)
    with pytest.raises(ValueError, match="speed"):
        R.runner.submit(KEY, ["s"], speed=2)
    with pytest.raises(ValueError, match="отрицательным"):
        R.runner.submit(KEY, ["s"], start_step=-1)


def test_старый_рецепт_без_хэша_восстанавливает_карту(monkeypatch):
    _record()
    path = save.recipe_path(KEY)
    data = json.loads(path.read_text("utf-8"))
    data.pop("code_sha256")
    path.write_text(json.dumps(data), "utf-8")
    sc = scenarios.get(KEY)
    assert R.verified_line_map(sc)                      # файл совпал с перерисовкой
    save.target_path(KEY).write_text(
        save.target_path(KEY).read_text("utf-8") + "# правка\n", "utf-8")
    scenarios.invalidate(KEY)
    assert R.verified_line_map(scenarios.get(KEY)) == {}   # рукой тронут — карты нет
