"""Снимок экрана у отклонений HOLD / LAYER / BRANCH; шаг у HOLD."""
import types

import pytest

from farm import config, control, resolve, scenarios, deviations as dv
from farm.context import DeviceContext
from farm.devices import runner as R
from farm.recorder import save as recorder_save


@pytest.fixture(autouse=True)
def _чисто(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    dv.deviations.clear()
    yield
    dv.deviations.clear()


def _пишет(serial, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def _падает(serial, path):
    raise RuntimeError("adb умер")


def _job():
    return R.Job(id="j1", scenario_key="k", scenario_name="К",
                 serial="s", device_name="D", params={})


SC_SRC = (
    "def run(job, record):\n"   # 1
    "    a = 1\n"               # 2
    "    record(job, 'x')\n"    # 3
)


def _из_сценария(monkeypatch, tmp_path, line_map):
    p = tmp_path / "sc.py"
    ns = {}
    exec(compile(SC_SRC, str(p), "exec"), ns)
    # индекс считается только по sc, что реально исполнялся (его передаёт
    # _execute), и только при совпадении code_sha256 рецепта с sc.sha256
    sc = types.SimpleNamespace(path=p, key="k", recorded=True, sha256="h")
    monkeypatch.setattr(recorder_save, "load_recipe", lambda k: {"code_sha256": "h"})
    monkeypatch.setattr(recorder_save, "load_line_map", line_map)
    j = _job()
    ns["run"](j, lambda job, m: R._record_hold(job, m, "", sc))
    return j


# ------------------------------------------------------------------ HOLD
def test_hold_со_снимком_и_шагом(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "save_screenshot", _пишет)
    _из_сценария(monkeypatch, tmp_path, lambda k: {3: 5})
    (d,) = dv.deviations.list()
    assert d["shot"] == "hold_1.jpg" and d["step_index"] == 5
    assert (tmp_path / "j1" / "hold_1.jpg").is_file()


def test_hold_второй_раз_не_затирает_первый(monkeypatch):
    monkeypatch.setattr(control, "save_screenshot", _пишет)
    j = _job()
    R._record_hold(j, "а")
    R._record_hold(j, "б")
    assert (tmp_path_f := config.ARTIFACTS_DIR / "j1" / "hold_2.jpg").is_file()
    assert tmp_path_f.parent.joinpath("hold_1.jpg").is_file()


def test_hold_снимок_упал_отклонение_есть(monkeypatch):
    monkeypatch.setattr(control, "save_screenshot", _падает)
    j = _job()
    R._record_hold(j, "а")
    (d,) = dv.deviations.list()
    assert d["shot"] == ""
    assert any("фото остановки не снялось" in s for s in j.lines)


def test_hold_пустая_карта_даёт_минус_один(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "save_screenshot", _пишет)
    _из_сценария(monkeypatch, tmp_path, lambda k: {})
    assert dv.deviations.list()[0]["step_index"] == -1


def test_hold_сбой_вычисления_шага(monkeypatch, tmp_path):
    monkeypatch.setattr(control, "save_screenshot", _пишет)

    def бомба(k):
        raise OSError("нет рецепта")
    j = _из_сценария(monkeypatch, tmp_path, бомба)
    (d,) = dv.deviations.list()
    assert d["step_index"] == -1 and d["shot"] == "hold_1.jpg"
    assert any("индекс шага не определён" in s for s in j.lines)


# ------------------------------------------------------------ LAYER / BRANCH
def _ctx(tmp_path, lines):
    return DeviceContext("s", logger=lines.append, artifacts_dir=tmp_path,
                         job_id="j1", scenario_key="k")


def _слой(monkeypatch, ctx):
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "tap", lambda x, y: None)
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "ocr", "Войти"))
    ctx.click_target(text=["Войти"])


def _ветка(monkeypatch, ctx):
    monkeypatch.setattr(ctx, "_screen_texts", lambda limit=5: ["Реклама"])
    monkeypatch.setattr(ctx, "current_app", lambda: "com.x")
    ctx._report_branch({"а": 1}, "никакая")


@pytest.mark.parametrize("действие", [_слой, _ветка])
def test_снимок_есть(monkeypatch, tmp_path, действие):
    monkeypatch.setattr(control, "save_screenshot", _пишет)
    lines = []
    действие(monkeypatch, _ctx(tmp_path, lines))
    (d,) = dv.deviations.list()
    assert d["shot"].endswith(".jpg") and (tmp_path / d["shot"]).is_file()
    assert d["step_index"] == -1


@pytest.mark.parametrize("действие", [_слой, _ветка])
def test_снимок_упал_шаг_жив(monkeypatch, tmp_path, действие):
    monkeypatch.setattr(control, "save_screenshot", _падает)
    lines = []
    действие(monkeypatch, _ctx(tmp_path, lines))
    (d,) = dv.deviations.list()
    assert d["shot"] == ""
    assert any("фото отклонения не снялось" in s for s in lines)


def test_без_папки_артефактов_снимка_нет(monkeypatch):
    """Общий корень не отдаётся через маршрут задачи — снимать незачем."""
    calls = []
    monkeypatch.setattr(control, "save_screenshot", lambda s, p: calls.append(p))
    lines = []
    ctx = DeviceContext("s", logger=lines.append, job_id="j1", scenario_key="k")
    assert ctx._deviation_shot("layer") == ""
    assert calls == [] and lines == []


def test_слой_снимок_один_раз_на_подпись(monkeypatch, tmp_path):
    snaps = []
    monkeypatch.setattr(control, "save_screenshot",
                        lambda s, p: (snaps.append(p), _пишет(s, p)))
    ctx = _ctx(tmp_path, [])
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    monkeypatch.setattr(ctx, "tap", lambda x, y: None)
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.6, "ocr", "Войти"))
    ctx.click_target(sel=[{"text": "А"}], text=["Войти"])
    ctx.click_target(sel=[{"text": "А"}], text=["Войти"])
    assert len(snaps) == 1
    (d,) = dv.deviations.list()
    assert d["hits"] == 2 and d["shot"]
    ctx.click_target(sel=[{"text": "Б"}], text=["Войти"])
    assert len(snaps) == 2
