"""`Deviation.miss`: что искал промахнувшийся click_target.

Цель едет на самом исключении / в вызове hold, а не лежит на контексте, —
поэтому чужое падение её получить не может.
"""
import json
import types

import pytest

from farm import config, control, resolve, scenarios, deviations as dv
from farm.context import DeviceContext, StepFailed, HOLD_RETRY, HOLD_SKIP
from farm.devices import runner as R
from farm.recorder import save as recorder_save

SEL = [{"text": "Войти"}, {"resourceId": "a:id/b"}]
ОЖИДАЕМО = {"sel": SEL, "text": ["Войти"], "img": "btn.png", "at": [10.0, 20.0]}


@pytest.fixture(autouse=True)
def _чисто(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    dv.deviations.clear()
    yield
    dv.deviations.clear()


class Ctx(DeviceContext):
    def __init__(self, **kw):
        super().__init__("s", logger=lambda m: None, **kw)

    def _settle(self):
        pass

    def _rescue(self):
        return False

    def tap(self, x, y):
        pass


def _нет(monkeypatch):
    monkeypatch.setattr(resolve, "resolve", lambda *a, **k: None)


def _есть(monkeypatch):
    monkeypatch.setattr(resolve, "resolve", lambda *a, **k: types.SimpleNamespace(
        layer="selector", detail="", x=1, y=2))


def _цель(**kw):
    return dict(sel=SEL, text=["Войти"], img="/x/y/btn.png", at=(10, 20), **kw)


def test_промах_без_hold_кладёт_цель_на_исключение(monkeypatch):
    _нет(monkeypatch)
    with pytest.raises(StepFailed) as e:
        Ctx().click_target(**_цель(), timeout=0)
    assert json.loads(e.value.miss) == ОЖИДАЕМО


def test_hold_получает_цель(monkeypatch):
    _нет(monkeypatch)
    got = []
    ctx = Ctx(hold=lambda что, miss="": got.append(miss) or HOLD_SKIP)
    ctx.click_target(**_цель(), timeout=0)
    assert json.loads(got[0]) == ОЖИДАЕМО


def test_одноаргументный_hold_работает(monkeypatch):
    _нет(monkeypatch)
    got = []
    ctx = Ctx(hold=lambda что: got.append(что) or HOLD_SKIP)
    ctx.click_target(**_цель(), timeout=0)
    assert len(got) == 1


def test_успешный_клик_не_протекает_в_чужое_падение(monkeypatch):
    _есть(monkeypatch)
    ctx = Ctx()
    ctx.click_target(**_цель(), timeout=0)
    with pytest.raises(StepFailed) as e:
        ctx.fail("другое")
    assert e.value.miss == ""


def test_пропущенный_человеком_клик_не_протекает(monkeypatch):
    _нет(monkeypatch)
    ctx = Ctx(hold=lambda что, miss="": HOLD_SKIP)
    ctx.click_target(**_цель(), timeout=0)
    with pytest.raises(StepFailed) as e:
        ctx.fail("другое")
    assert e.value.miss == ""


def test_странные_входы_нормализуются(monkeypatch):
    _нет(monkeypatch)
    with pytest.raises(StepFailed) as e:
        Ctx().click_target(sel=None, text="одна", img=None, at=(1, 2), timeout=0)
    assert json.loads(e.value.miss) == {"sel": [], "text": ["одна"], "img": "", "at": [1.0, 2.0]}
    with pytest.raises(StepFailed) as e:
        Ctx().click_target(sel=[{"a": object()}], timeout=0)
    assert json.loads(e.value.miss)["at"] == []


def test_record_hold_пишет_miss(monkeypatch):
    monkeypatch.setattr(control, "save_screenshot", lambda s, p: None)
    monkeypatch.setattr(scenarios, "get", lambda k: None)
    j = R.Job(id="j1", scenario_key="k", scenario_name="К",
              serial="s", device_name="D", params={})
    R._record_hold(j, "что", '{"sel": []}')
    (d,) = dv.deviations.list()
    assert d["miss"] == '{"sel": []}'


SC_SRC = (
    "def run(ctx):\n"
    "    ctx.click_target(text=['Войти'], timeout=0)\n"
)


def _execute(monkeypatch, tmp_path, src):
    p = tmp_path / "sc.py"
    ns = {}
    exec(compile(src, str(p), "exec"), ns)
    sc = types.SimpleNamespace(module=types.SimpleNamespace(run=ns["run"]), path=str(p))
    monkeypatch.setattr(scenarios, "get", lambda k: sc)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "art")
    monkeypatch.setattr(R.control, "clear_logcat", lambda s: None)
    monkeypatch.setattr(R.registry, "acquire", lambda s, j: True)
    monkeypatch.setattr(R.registry, "release", lambda s, j: None)
    monkeypatch.setattr(R, "_collect_failure_artifacts", lambda j, d: None)
    monkeypatch.setattr(recorder_save, "load_line_map", lambda k: {})
    monkeypatch.setattr(config, "HOLD", False)  # без остановки на человеке
    monkeypatch.setattr(DeviceContext, "_settle", lambda self: None)
    monkeypatch.setattr(DeviceContext, "_rescue", lambda self: False)
    _нет(monkeypatch)
    j = R.Job(id="j1", scenario_key="k", scenario_name="К",
              serial="s", device_name="D", params={})
    R._execute(j)
    return j


def test_execute_пишет_miss_у_FAIL(monkeypatch, tmp_path):
    _execute(monkeypatch, tmp_path, SC_SRC)
    (d,) = dv.deviations.list()
    assert d["kind"] == dv.FAIL
    assert json.loads(d["miss"])["text"] == ["Войти"]


def test_execute_чужое_падение_без_miss(monkeypatch, tmp_path):
    _execute(monkeypatch, tmp_path, "def run(ctx):\n    raise ValueError('x')\n")
    (d,) = dv.deviations.list()
    assert d["miss"] == ""
