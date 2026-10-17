"""Индекс упавшего шага: строка сценария из трейсбэка → шаг рецепта."""
import traceback
import types

import pytest

from farm import deviations as dv
from farm.devices import runner as R
from farm.recorder import save as recorder_save


@pytest.fixture(autouse=True)
def _чисто():
    dv.deviations.clear()
    yield
    dv.deviations.clear()

SRC = (
    "def helper():\n"          # 1
    "    raise ValueError('x')\n"  # 2
    "def run(ctx):\n"          # 3
    "    a = 1\n"              # 4
    "    helper()\n"           # 5
)


def _tb(path, src=SRC, fn="run"):
    ns = {}
    exec(compile(src, str(path), "exec"), ns)
    try:
        ns[fn](None)
    except ValueError as e:
        return traceback.extract_tb(e.__traceback__)


def test_берётся_строка_сценария_а_не_глубже(tmp_path):
    p = tmp_path / "sc.py"
    frames = _tb(p)
    # самый глубокий кадр — helper (стр. 2), но в карте он тоже есть: берём
    # самый внутренний кадр СЦЕНАРИЯ, и это как раз он
    assert R.step_index_from_frames(frames, p, {5: 3, 2: 7}) == 7


def test_кадры_чужих_файлов_глубже_сценария_пропускаются(tmp_path):
    p = tmp_path / "sc.py"
    other = tmp_path / "farm_ctx.py"
    ns = {}
    exec(compile("def click():\n    raise ValueError('x')\n", str(other), "exec"), ns)
    sc = {"click": ns["click"]}
    exec(compile("def run(ctx):\n    a = 1\n    click()\n", str(p), "exec"), sc)
    try:
        sc["run"](None)
    except ValueError as e:
        frames = traceback.extract_tb(e.__traceback__)
    assert frames[-1].filename == str(other)
    assert R.step_index_from_frames(frames, p, {3: 4}) == 4


def test_чужой_файл_и_пустая_карта_дают_минус_один(tmp_path):
    p = tmp_path / "sc.py"
    frames = _tb(p)
    assert R.step_index_from_frames(frames, tmp_path / "other.py", {5: 1}) == -1
    assert R.step_index_from_frames(frames, p, {}) == -1
    assert R.step_index_from_frames(frames, p, {99: 1}) == -1


def test_из_исключения(tmp_path):
    p = tmp_path / "sc.py"
    ns = {}
    exec(compile(SRC, str(p), "exec"), ns)
    try:
        ns["run"](None)
    except ValueError as e:
        assert R.step_index_from_exc(e, p, {2: 2, 5: 9}) == 2


def _job():
    return R.Job(id="j1", scenario_key="k", scenario_name="К",
                 serial="s", device_name="D", params={})


def test_запись_падения_с_кадром_и_шагом(tmp_path):
    (tmp_path / "99_failure.jpg").write_bytes(b"x")
    j = _job()
    j.error = "boom"
    R._record_failure(j, tmp_path, step_index=3)
    (d,) = dv.deviations.list()
    assert d["step_index"] == 3 and d["shot"] == "99_failure.jpg"


def test_запись_падения_без_файла_кадра(tmp_path):
    j = _job()
    j.error = "boom"
    R._record_failure(j, tmp_path)
    (d,) = dv.deviations.list()
    assert d["shot"] == "" and d["step_index"] == -1


SC_SRC = (
    "def run(ctx):\n"                       # 1
    "    from farm.context import StepFailed\n"  # 2
    "    raise StepFailed('нет кнопки')\n"  # 3
)


def _прогон(monkeypatch, tmp_path, line_map=None, boom=None, recipe_sha="h",
            sc_sha="h", recorded=True):
    from farm import config, control, scenarios
    p = tmp_path / "sc.py"
    ns = {}
    exec(compile(SC_SRC, str(p), "exec"), ns)
    sc = types.SimpleNamespace(module=types.SimpleNamespace(run=ns["run"]),
                               path=str(p), key="k", recorded=recorded,
                               sha256=sc_sha)
    recipe = {"code_sha256": recipe_sha} if recipe_sha else {}
    monkeypatch.setattr(recorder_save, "load_recipe", lambda k: recipe)
    monkeypatch.setattr(scenarios, "get", lambda k: sc)
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "art")
    monkeypatch.setattr(control, "clear_logcat", lambda s: None)
    monkeypatch.setattr(R.registry, "acquire", lambda s, j: True)
    monkeypatch.setattr(R.registry, "release", lambda s, j: None)
    monkeypatch.setattr(R, "_collect_failure_artifacts", lambda j, d: None)
    if boom:
        def _raise(k):
            raise boom
        monkeypatch.setattr(recorder_save, "load_line_map", _raise)
    else:
        monkeypatch.setattr(recorder_save, "load_line_map",
                            lambda k: line_map or {})
    j = _job()
    R._execute(j)
    return j


def test_execute_кладёт_индекс_в_отклонение(monkeypatch, tmp_path):
    j = _прогон(monkeypatch, tmp_path, line_map={3: 5})
    assert j.status == R.FAILED
    (d,) = dv.deviations.list()
    assert d["step_index"] == 5


def test_сбой_расчёта_индекса_логируется_и_не_ломает_запись(monkeypatch, tmp_path):
    j = _прогон(monkeypatch, tmp_path, boom=RuntimeError("карта битая"))
    (d,) = dv.deviations.list()
    assert d["step_index"] == -1
    assert any("индекс шага не определён: карта битая" in l for l in j.lines)


# ----------------------------------------------- целостность: code_sha256

def _idx():
    (d,) = dv.deviations.list()
    return d["step_index"]


def test_хеш_совпал_индекс_найден(monkeypatch, tmp_path):
    _прогон(monkeypatch, tmp_path, line_map={3: 5})
    assert _idx() == 5


def test_хеш_не_совпал_при_годной_карте_минус_один(monkeypatch, tmp_path):
    _прогон(monkeypatch, tmp_path, line_map={3: 5}, recipe_sha="другой")
    assert _idx() == -1


def test_у_рецепта_нет_ключа_минус_один(monkeypatch, tmp_path):
    _прогон(monkeypatch, tmp_path, line_map={3: 5}, recipe_sha="")
    assert _idx() == -1


def test_пустые_хеши_рецепта_и_сценария_не_равны_минус_один(monkeypatch, tmp_path):
    # "" == "" не должно считаться совпадением, даже при годной карте
    _прогон(monkeypatch, tmp_path, line_map={3: 5}, recipe_sha="", sc_sha="")
    assert _idx() == -1


def test_сирота_не_из_конструктора_минус_один(monkeypatch, tmp_path):
    _прогон(monkeypatch, tmp_path, line_map={3: 5}, recorded=False)
    assert _idx() == -1


def test_рукописный_без_рецепта_минус_один(monkeypatch, tmp_path):
    _прогон(monkeypatch, tmp_path, line_map={}, recipe_sha="", recorded=False)
    assert _idx() == -1


def test_рецепт_перезаписан_после_загрузки_минус_один(monkeypatch, tmp_path):
    # конструктор сохранил новый код посреди прогона: в рецепте уже новый хеш,
    # а исполняется старый модуль (sc.sha256 старый)
    _прогон(monkeypatch, tmp_path, line_map={3: 5}, recipe_sha="новый", sc_sha="старый")
    assert _idx() == -1


def test_hold_то_же_правило_и_тот_же_sc(monkeypatch, tmp_path):
    from farm import control, scenarios
    monkeypatch.setattr(control, "save_screenshot", lambda s, p: None)
    monkeypatch.setattr(recorder_save, "load_line_map", lambda k: {5: 2})
    # свежий scenarios.get не должен участвовать
    monkeypatch.setattr(scenarios, "get", lambda k: pytest.fail("get"))
    ns = {}
    p = tmp_path / "sc.py"
    exec(compile("def run(j, rec):\n    a = 1\n    b = 2\n    c = 3\n"
                 "    rec(j)\n", str(p), "exec"), ns)

    def идти(recipe, sha):
        dv.deviations.clear()
        monkeypatch.setattr(recorder_save, "load_recipe", lambda k: recipe)
        sc = types.SimpleNamespace(path=str(p), key="k", recorded=True, sha256=sha)
        ns["run"](_job(), lambda j: R._record_hold(j, "x", "", sc))
        return _idx()

    assert идти({"code_sha256": "h"}, "h") == 2
    assert идти({"code_sha256": "z"}, "h") == -1
    assert идти({}, "h") == -1


def test_hold_без_sc_минус_один(monkeypatch, tmp_path):
    from farm import control
    monkeypatch.setattr(control, "save_screenshot", lambda s, p: None)
    R._record_hold(_job(), "x")
    assert _idx() == -1


def test_scenario_sha256_это_хеш_загруженных_байт(monkeypatch, tmp_path):
    import hashlib
    from farm import config, scenarios
    monkeypatch.setattr(config, "SCENARIOS_DIR", tmp_path)
    monkeypatch.setattr(scenarios, "_cache", {})
    monkeypatch.setattr(scenarios, "_stamps", {})
    raw = "# кодировка\ndef run(ctx):\n    pass\n".encode("utf-8")
    (tmp_path / "a.py").write_bytes(raw)
    (tmp_path / "bad.py").write_bytes(b"def run(:\n")
    assert scenarios.get("a").sha256 == hashlib.sha256(raw).hexdigest()
    assert scenarios.get("bad").sha256 == ""


def test_сбой_поиска_сценария_не_держит_устройство(monkeypatch, tmp_path):
    from farm import config, control, scenarios
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path / "art")
    monkeypatch.setattr(control, "clear_logcat", lambda s: None)
    отпущено = []
    monkeypatch.setattr(R.registry, "acquire", lambda s, j: True)
    monkeypatch.setattr(R.registry, "release", lambda s, j: отпущено.append((s, j)))
    monkeypatch.setattr(R, "_collect_failure_artifacts", lambda j, d: None)

    def бомба(k):
        raise OSError("диск отвалился")
    monkeypatch.setattr(scenarios, "get", бомба)
    j = _job()
    R._execute(j)
    assert j.status == R.FAILED and "диск отвалился" in j.error
    assert отпущено == [("s", "j1")] and j.finished_at is not None
