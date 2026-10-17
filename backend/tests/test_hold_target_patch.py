"""Исправленная цель при ответе «повторить»: человек показал, куда кликать.

Патч проверяется в одном месте (`normalize_target`), едет на Job вместе с
решением и забирается click_target ровно один раз.
"""
import json
import threading
import time
import types

import pytest
from fastapi import HTTPException

from farm import config, control, resolve, scenarios, deviations as dv
from farm.api import jobs as api
from farm.context import (DeviceContext, HOLD_DROP, HOLD_RETRY, HOLD_SKIP,
                          normalize_target)
from farm.devices import runner as R
from farm.recorder import save as recorder_save

SEL = [{"text": "Войти"}]


# ------------------------------------------------------------ normalize_target

def test_normalize_принимает_годное():
    raw = {"sel": SEL, "text": ["Ок"], "img": "btn.png", "at": [0, 1.0]}
    assert normalize_target(raw) == {"sel": SEL, "text": ["Ок"], "img": "btn.png",
                                     "at": [0.0, 1.0]}
    assert normalize_target({"text": ["a"]}) == {"text": ["a"]}
    assert normalize_target({}) == {}
    assert normalize_target(None) == {}


@pytest.mark.parametrize("bad", [
    "строка", [1], {"zzz": 1},
    {"sel": "x"}, {"sel": ["x"]}, {"sel": {"a": 1}},
    {"text": "x"}, {"text": [1]},
    {"img": 5}, {"img": ""}, {"img": "a/b.png"}, {"img": "a\\b.png"},
    {"img": ".."}, {"img": "../x.png"},
    {"img": "a\x00.png"}, {"img": "C:x.png"}, {"img": "a" * 252 + ".png"},
    {"at": [0.5]}, {"at": [0.1, 0.2, 0.3]}, {"at": ["a", "b"]},
    {"at": [1.5, 0.5]}, {"at": [0.5, -0.1]}, {"at": [True, 0.5]},
    {"at": [float("nan"), 0.5]}, {"at": "ab"},
])
def test_normalize_отвергает_плохое(bad):
    with pytest.raises(ValueError):
        normalize_target(bad)


# ------------------------------------------------------------------ decide

@pytest.fixture
def задача():
    dv.deviations.clear()
    job = R.Job(id="j1", scenario_key="k", scenario_name="К",
                serial="s", device_name="D", params={})
    job.status = R.HELD
    R.runner.jobs[job.id] = job
    R.runner.order.append(job.id)
    yield job
    R.runner.jobs.pop(job.id, None)
    R.runner.order.remove(job.id)
    dv.deviations.clear()


def test_decide_с_целью_сохраняет_и_будит(задача):
    assert R.runner.decide("j1", HOLD_RETRY, {"at": [0.5, 0.25]}) is True
    assert задача.target_patch == {"at": [0.5, 0.25]}
    assert задача.decision == HOLD_RETRY
    assert задача._decided.is_set()


def test_decide_пустая_цель_это_без_патча(задача):
    assert R.runner.decide("j1", HOLD_RETRY, {}) is True
    assert задача.target_patch is None


@pytest.mark.parametrize("решение", [HOLD_SKIP, HOLD_DROP])
def test_decide_цель_только_с_retry(задача, решение):
    with pytest.raises(ValueError):
        R.runner.decide("j1", решение, {"at": [0.5, 0.5]})
    assert задача.decision == "" and задача.target_patch is None
    assert not задача._decided.is_set()


def test_decide_плохая_цель_не_трогает_задачу(задача):
    with pytest.raises(ValueError):
        R.runner.decide("j1", HOLD_RETRY, {"img": "../x"})
    assert задача.decision == "" and задача.target_patch is None
    assert not задача._decided.is_set() and задача.lines == []


def test_decide_не_стоящая_задача(задача):
    задача.status = R.RUNNING
    assert R.runner.decide("j1", HOLD_RETRY, {"at": [0.5, 0.5]}) is False
    assert задача.target_patch is None


# ------------------------------------------------------------ click_target

class Ctx(DeviceContext):
    def __init__(self, **kw):
        super().__init__("s", logger=lambda m: None, **kw)
        self.lines = []
        self._logger = self.lines.append

    def _settle(self):
        pass

    def _rescue(self):
        return False

    def tap(self, x, y):
        pass


def _resolve(monkeypatch, ответы):
    вызовы = []

    def fake(ctx, **kw):
        вызовы.append(kw)
        return ответы.pop(0)

    monkeypatch.setattr(resolve, "resolve", fake)
    return вызовы


HIT = types.SimpleNamespace(layer="selector", detail="", x=1, y=2)


def test_патч_заменяет_только_указанные_ключи(monkeypatch):
    вызовы = _resolve(monkeypatch, [None, HIT])
    патчи = [{"text": ["Новый"], "at": [0.5, 0.5]}]
    ctx = Ctx(hold=lambda что: HOLD_RETRY,
              take_target_patch=lambda: патчи.pop() if патчи else None)
    ctx.click_target(sel=SEL, text=["Старый"], img="b.png", at=(1, 2), timeout=0)
    assert вызовы[0]["text"] == ["Старый"] and вызовы[0]["at"] == (1, 2)
    assert вызовы[1]["text"] == ["Новый"] and вызовы[1]["at"] == [0.5, 0.5]
    assert вызовы[1]["sel"] == SEL and вызовы[1]["img"] == "b.png"
    assert sum("заменена человеком" in l for l in ctx.lines) == 1


def test_патч_забирается_один_раз_и_держится_на_следующих_попытках(monkeypatch):
    """Второй hold без патча остаётся с уже исправленной целью, не с исходной."""
    вызовы = _resolve(monkeypatch, [None, None, HIT])
    патчи = [{"text": ["Новый"]}]
    взято = []

    def взять():
        взято.append(1)
        return патчи.pop() if патчи else None

    ctx = Ctx(hold=lambda что, miss="": HOLD_RETRY, take_target_patch=взять)
    ctx.click_target(text=["Старый"], timeout=0)
    assert [v["text"] for v in вызовы] == [["Старый"], ["Новый"], ["Новый"]]
    assert len(взято) == 2


def test_второй_промах_сообщает_исправленную_цель(monkeypatch):
    _resolve(monkeypatch, [None, None])
    miss_ы = []
    решения = iter([HOLD_RETRY, HOLD_DROP])

    def hold(что, miss=""):
        miss_ы.append(miss)
        return next(решения)

    патчи = [{"text": ["Новый"]}]
    ctx = Ctx(hold=hold, take_target_patch=lambda: патчи.pop() if патчи else None)
    with pytest.raises(Exception) as e:
        ctx.click_target(text=["Старый"], timeout=0)
    assert json.loads(miss_ы[0])["text"] == ["Старый"]
    assert json.loads(miss_ы[1])["text"] == ["Новый"]
    assert json.loads(e.value.miss)["text"] == ["Новый"]
    assert "Новый" in str(e.value)


def test_патч_не_течёт_в_следующий_вызов(monkeypatch):
    вызовы = _resolve(monkeypatch, [None, HIT, HIT])
    патчи = [{"text": ["Новый"]}]
    ctx = Ctx(hold=lambda что: HOLD_RETRY,
              take_target_patch=lambda: патчи.pop() if патчи else None)
    ctx.click_target(text=["Старый"], timeout=0)
    ctx.click_target(text=["Старый"], timeout=0)
    assert вызовы[2]["text"] == ["Старый"]


def test_патч_не_берётся_при_skip(monkeypatch):
    _resolve(monkeypatch, [None])
    взято = []
    ctx = Ctx(hold=lambda что: HOLD_SKIP, take_target_patch=lambda: взято.append(1))
    ctx.click_target(text=["Старый"], timeout=0)
    assert взято == []


# ---------------------------------------------------- _execute целиком (glue)

SC_SRC = "def run(ctx):\n    ctx.click_target(text=['Войти'], timeout=0)\n"


def test_execute_с_остановкой_и_патчем(monkeypatch, tmp_path):
    p = tmp_path / "sc.py"
    ns = {}
    exec(compile(SC_SRC, str(p), "exec"), ns)
    sc = types.SimpleNamespace(module=types.SimpleNamespace(run=ns["run"]), path=str(p))
    monkeypatch.setattr(scenarios, "get", lambda k: sc)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "art")
    monkeypatch.setattr(config, "HOLD", True)
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 5.0)
    monkeypatch.setattr(R.control, "clear_logcat", lambda s: None)
    monkeypatch.setattr(control, "save_screenshot", lambda s, p: None)
    monkeypatch.setattr(R.registry, "acquire", lambda s, j: True)
    monkeypatch.setattr(R.registry, "release", lambda s, j: None)
    monkeypatch.setattr(R, "_collect_failure_artifacts", lambda j, d: None)
    monkeypatch.setattr(recorder_save, "load_line_map", lambda k: {})
    monkeypatch.setattr(DeviceContext, "_settle", lambda self: None)
    monkeypatch.setattr(DeviceContext, "_rescue", lambda self: False)
    вызовы = _resolve(monkeypatch, [None, HIT])
    monkeypatch.setattr(DeviceContext, "tap", lambda self, x, y: None)
    dv.deviations.clear()
    j = R.Job(id="jx", scenario_key="k", scenario_name="К",
              serial="s", device_name="D", params={})
    R.runner.jobs[j.id] = j
    итог = []

    def человек():
        конец = time.time() + 5
        while time.time() < конец and j.status != R.HELD:
            time.sleep(0.01)
        итог.append(R.runner.decide("jx", HOLD_RETRY, {"text": ["Иначе"]}))

    t = threading.Thread(target=человек)
    t.start()
    try:
        R._execute(j)
    finally:
        t.join()
        R.runner.jobs.pop("jx", None)
    assert итог == [True]
    assert j.status == R.PASSED, j.lines
    assert вызовы[1]["text"] == ["Иначе"]
    assert j.target_patch is None
    (d,) = [d for d in dv.deviations.list() if d["kind"] == dv.HOLD]
    assert json.loads(d["miss"])["text"] == ["Войти"]
    dv.deviations.clear()


# --------------------------------------------------------------------- API

def test_api_decide_с_целью(задача):
    assert api.decide_job("j1", {"decision": "retry",
                                 "target": {"at": [0.1, 0.2]}}) == {"ok": True}
    assert задача.target_patch == {"at": [0.1, 0.2]}


def test_api_decide_плохая_цель_400(задача):
    with pytest.raises(HTTPException) as e:
        api.decide_job("j1", {"decision": "retry", "target": {"at": [9, 9]}})
    assert e.value.status_code == 400


def test_api_decide_не_стоит_409(задача):
    задача.status = R.RUNNING
    with pytest.raises(HTTPException) as e:
        api.decide_job("j1", {"decision": "retry", "target": {"at": [0.1, 0.2]}})
    assert e.value.status_code == 409


# ------------------------------------------------- review fixes (hold/decide)

class _СледитЗаСтатусом(R.Job):
    """Запоминает, в каком состоянии были поля в миг, когда статус стал HELD."""
    def __setattr__(self, name, value):
        if name == "status" and value == R.HELD:
            object.__setattr__(self, "снимок", (
                self.decision, self.target_patch, self._decided.is_set()))
        object.__setattr__(self, name, value)


def _держать(monkeypatch, job):
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 0.01)
    monkeypatch.setattr(R, "_record_hold", lambda *a, **k: None)
    return R._hold(job, "промах")


def test_hold_статус_HELD_ставится_после_сброса_решения(monkeypatch):
    job = _СледитЗаСтатусом(id="j9", scenario_key="k", scenario_name="К",
                            serial="s", device_name="D", params={})
    job.decision, job.target_patch = HOLD_RETRY, {"at": [0.1, 0.1]}
    job._decided.set()
    _держать(monkeypatch, job)
    assert job.снимок == ("", None, False)


def test_hold_старт_чистит_чужой_патч(monkeypatch):
    job = R.Job(id="j8", scenario_key="k", scenario_name="К",
                serial="s", device_name="D", params={})
    job.target_patch = {"at": [0.9, 0.9]}
    seen = []
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 0.01)
    monkeypatch.setattr(R, "_record_hold",
                        lambda j, *a, **k: seen.append(j.target_patch))
    R._hold(job, "промах")
    assert seen == [None]


def test_decide_двойной_клик_второй_ничего_не_меняет(задача):
    assert R.runner.decide("j1", HOLD_RETRY, {"at": [0.5, 0.25]}) is True
    assert R.runner.decide("j1", HOLD_RETRY) is False
    assert R.runner.decide("j1", HOLD_SKIP) is False
    assert задача.decision == HOLD_RETRY
    assert задача.target_patch == {"at": [0.5, 0.25]}


@pytest.mark.parametrize("решение", ["skip", "drop"])
def test_api_decide_skip_drop_с_целью_400(задача, решение):
    with pytest.raises(HTTPException) as e:
        api.decide_job("j1", {"decision": решение, "target": {"at": [0.1, 0.2]}})
    assert e.value.status_code == 400


def test_hold_строка_ожидания_в_журнале_до_статуса_HELD(monkeypatch):
    """Иначе decide мог дописать «человек решил» раньше «жду решения»."""
    class _Смотрит(R.Job):
        def __setattr__(self, name, value):
            if name == "status" and value == R.HELD:
                object.__setattr__(self, "строки", list(self.lines))
            object.__setattr__(self, name, value)
    job = _Смотрит(id="j7", scenario_key="k", scenario_name="К",
                   serial="s", device_name="D", params={})
    _держать(monkeypatch, job)
    assert any("жду решения человека" in s for s in job.строки)


# ------------------------------------------------- allowlist ключей селектора

VALID_SEL = [
    ("text", "a"), ("textContains", "a"), ("textStartsWith", "a"),
    ("className", "android.widget.Button"), ("description", "a"),
    ("descriptionContains", "a"), ("descriptionStartsWith", "a"),
    ("packageName", "com.a"), ("resourceId", "com.a:id/b"),
    ("index", 0), ("instance", 2), ("clickable", True),
]

# regex-ключи и прочие bool-флаги панель не генерирует: `*Matches` в патче
# от клиента — это регулярка, исполняемая на устройстве (ReDoS), не пускаем
REJECTED_SEL = [
    ("textMatches", "a.*"), ("classNameMatches", ".*B"),
    ("descriptionMatches", "a.*"), ("packageNameMatches", "com.*"),
    ("resourceIdMatches", ".*/b"), ("checkable", True), ("checked", False),
    ("longClickable", False), ("scrollable", True), ("enabled", True),
    ("focusable", False), ("focused", True), ("selected", False),
]


@pytest.mark.parametrize("key,value", REJECTED_SEL)
def test_sel_regex_и_лишние_флаги_отвергаются(key, value):
    with pytest.raises(ValueError, match=key):
        normalize_target({"sel": [{key: value}]})


@pytest.mark.parametrize("key,value", VALID_SEL)
def test_sel_разрешённый_ключ_проходит(key, value):
    assert normalize_target({"sel": [{key: value}]}) == {"sel": [{key: value}]}


def test_sel_допустимые_ключи_известны_uiautomator2():
    u2 = pytest.importorskip("uiautomator2")
    from uiautomator2._selector import Selector
    for key, value in VALID_SEL:
        Selector(**{key: value})  # ReferenceError на неизвестном ключе


@pytest.mark.parametrize("bad,key", [
    ({"zzz": "a"}, "zzz"),
    ({"mask": 1}, "mask"),
    ({"childOrSibling": []}, "childOrSibling"),
    ({"instance": "1"}, "instance"),
    ({"instance": True}, "instance"),
    ({"index": 1.5}, "index"),
    ({"text": 5}, "text"),
    ({"clickable": 1}, "clickable"),
    ({"text": {"a": 1}}, "text"),
    ({"resourceId": ["a"]}, "resourceId"),
    ({"text": "x" * 2001}, "text"),
])
def test_sel_плохой_ключ_или_значение(bad, key):
    with pytest.raises(ValueError, match=key):
        normalize_target({"sel": [bad]})


def test_sel_пустой_словарь_и_не_словарь_и_много():
    with pytest.raises(ValueError):
        normalize_target({"sel": [{}]})
    with pytest.raises(ValueError):
        normalize_target({"sel": [{"text": "a"}, "x"]})
    assert len(normalize_target({"sel": [{"text": "a"}] * 8})["sel"]) == 8
    with pytest.raises(ValueError):
        normalize_target({"sel": [{"text": "a"}] * 9})
    assert normalize_target({"sel": [{"text": "x" * 2000}]})
    assert normalize_target({"text": ["y" * 2000] * 20})
    with pytest.raises(ValueError):
        normalize_target({"text": ["y" * 2001]})
    with pytest.raises(ValueError):
        normalize_target({"text": ["y"] * 21})


@pytest.mark.parametrize("raw", [
    {"sel": [], "text": []}, {"sel": []}, {"text": []},
])
def test_целиком_пустая_цель_отвергается(raw):
    # пустая цель роняла resolve сырым ValueError внутри задачи
    with pytest.raises(ValueError, match="пуст"):
        normalize_target(raw)


def test_пустой_sel_допустим_если_есть_другая_часть():
    assert normalize_target({"sel": [], "at": [0.1, 0.2]})["at"] == [0.1, 0.2]
    assert normalize_target({"sel": [], "text": ["a"]})["text"] == ["a"]


def test_api_decide_плохой_ключ_селектора_400_и_задача_ждёт(задача):
    with pytest.raises(HTTPException) as e:
        api.decide_job("j1", {"decision": "retry",
                              "target": {"sel": [{"zzz": "a"}]}})
    assert e.value.status_code == 400 and "zzz" in e.value.detail
    assert задача.decision == "" and задача.target_patch is None
    assert not задача._decided.is_set() and задача.status == R.HELD


# ------------------------------------------------------------ hold_repairable

def _рецепт(monkeypatch, steps):
    monkeypatch.setattr(recorder_save, "load_recipe",
                        lambda key: {"steps": steps} if key == "k" else None)


CLICK = {"kind": "click", "selector": {"args": 'text="Войти"'}}


@pytest.mark.parametrize("step, ok", [
    ({**CLICK, "texts": ["Войти"]}, True),
    ({**CLICK, "crop": "05_click.png"}, True),
    ({**CLICK, "point": [0.5, 0.5]}, True),
    (CLICK, False),                                   # рендерится в ctx.click — патч не примет
    ({"kind": "tap", "args": {"x": 0.1, "y": 0.2}}, False),
    ({"kind": "click", "texts": ["a"]}, False),        # без селектора
    ("мусор", False),
])
def test_hold_repairable_зеркалит_repairPlan(monkeypatch, step, ok):
    _рецепт(monkeypatch, [step])
    assert R.hold_repairable("k", 0) is ok


def test_hold_repairable_без_рецепта_и_за_краем(monkeypatch):
    _рецепт(monkeypatch, [{**CLICK, "texts": ["a"]}])
    assert R.hold_repairable("k", 1) is False
    assert R.hold_repairable("k", -1) is False
    assert R.hold_repairable("", 0) is False
    assert R.hold_repairable("чужой", 0) is False


def test_repairable_в_to_dict_только_у_ждущей_не_вслепую(monkeypatch):
    _рецепт(monkeypatch, [{**CLICK, "texts": ["a"]}])
    job = R.Job(id="j", scenario_key="k", scenario_name="k", serial="s",
                device_name="d", params={})
    job.step_index = 0
    job.status = R.RUNNING
    assert job.to_dict()["repairable"] is False
    job.status = R.HELD
    assert job.to_dict()["repairable"] is True
    job.held_kind = "blind"
    assert job.to_dict()["repairable"] is False
