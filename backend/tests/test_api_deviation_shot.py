"""API снимка и дампа отклонения: только метаданные и сохранённые артефакты."""
import base64
import json
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

from farm import config, control, deviations as dv
from farm.api import deviations as api
from farm.devices import runner as R

XML = ('<?xml version="1.0"?><hierarchy rotation="0">'
       '<node index="0" text="ОК" resource-id="a:id/ok" class="android.widget.Button" '
       'package="a" content-desc="" clickable="true" enabled="true" '
       'bounds="[100,200][300,400]"/></hierarchy>')


class _R:
    def __init__(self, code, body):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class _Клиент:
    """TestClient недоступен без httpx: зовём обработчики напрямую."""

    def get(self, path):
        _, _, _, iid, what = path.split("/")
        fn = {"shot": api.deviation_shot, "dump": api.deviation_dump}[what]
        try:
            return _R(200, fn(iid))
        except HTTPException as e:
            return _R(e.status_code, {"detail": e.detail})


@pytest.fixture
def cl(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    dv.deviations.clear()
    yield _Клиент()
    dv.deviations.clear()


def _add(kind=dv.FAIL, job="j1", shot="99_failure.jpg", miss=""):
    dv.deviations.record(kind, "T", job_id=job, scenario_key="k",
                         scenario_name="Сц", shot=shot, miss=miss, step_index=3,
                         device_name="Пикси")
    return dv.deviations.list()[0]["id"]


def _files(tmp_path, files, job="j1"):
    """files: имя файла -> содержимое (bytes или str)."""
    d = tmp_path / job
    d.mkdir(parents=True, exist_ok=True)
    for n, b in files.items():
        (d / n).write_bytes(b if isinstance(b, bytes) else b.encode())
    return d


def test_get_unknown_none():
    assert dv.deviations.get("нет") is None


def test_get_known(cl):
    i = _add()
    assert dv.deviations.get(i).id == i


def test_shot_unknown_404(cl):
    assert cl.get("/api/deviations/нет/shot").status_code == 404


def test_shot_no_shot_404(cl):
    assert cl.get(f"/api/deviations/{_add(shot='')}/shot").status_code == 404


def test_shot_file_missing_404(cl):
    assert cl.get(f"/api/deviations/{_add()}/shot").status_code == 404


def test_shot_traversal_404(cl, tmp_path):
    (tmp_path / "x").write_bytes(b"1")
    i = _add(shot="../x")
    assert cl.get(f"/api/deviations/{i}/shot").status_code == 404


def test_shot_ok(cl, tmp_path):
    _files(tmp_path, {"99_failure.jpg": b"jpg"})
    i = _add(miss=json.dumps({"sel": ["a"], "at": [1, 2]}))
    r = cl.get(f"/api/deviations/{i}/shot")
    assert r.status_code == 200
    j = r.json()
    assert j["url"] == "/api/jobs/j1/artifacts/99_failure.jpg"
    assert j["miss"] == {"sel": ["a"], "at": [1, 2]}
    assert j["step_index"] == 3 and j["job_id"] == "j1"
    assert j["shot"] == "99_failure.jpg" and j["kind"] == dv.FAIL
    assert "Сц" in j["alt"]


@pytest.mark.parametrize("miss", ["{плохо", "", "[1]"])
def test_shot_bad_miss(cl, tmp_path, miss):
    _files(tmp_path, {"99_failure.jpg": b"jpg"})
    r = cl.get(f"/api/deviations/{_add(miss=miss)}/shot")
    assert r.json()["miss"] == {}


def _dump_files(tmp_path, size=True):
    f = {"99_failure.jpg": b"\xff\xd8jpg", "failure_hierarchy.xml": XML}
    if size:
        f["failure_size.json"] = json.dumps({"width": 1080, "height": 2400})
    _files(tmp_path, f)


def test_dump_ok(cl, tmp_path):
    _dump_files(tmp_path)
    r = cl.get(f"/api/deviations/{_add()}/dump")
    assert r.status_code == 200
    j = r.json()
    assert (j["width"], j["height"]) == (1080, 2400)
    assert j["screenshot"] == "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8jpg").decode()
    assert j["nodes"]


def test_dump_unknown_404(cl):
    assert cl.get("/api/deviations/нет/dump").status_code == 404


def test_dump_no_hierarchy_404(cl, tmp_path):
    _files(tmp_path, {"99_failure.jpg": b"j"})
    assert cl.get(f"/api/deviations/{_add()}/dump").status_code == 404


def test_dump_non_fail_without_hierarchy_404(cl, tmp_path):
    _dump_files(tmp_path)
    i = _add(kind=dv.HOLD, job="j2")
    assert cl.get(f"/api/deviations/{i}/dump").status_code == 404


def test_dump_no_size_404(cl, tmp_path):
    _dump_files(tmp_path, size=False)
    r = cl.get(f"/api/deviations/{_add()}/dump")
    assert r.status_code == 404 and "размер экрана не сохранён" in r.json()["detail"]


def test_dump_bad_size_404(cl, tmp_path):
    _dump_files(tmp_path)
    (tmp_path / "j1" / "failure_size.json").write_text("{", "utf-8")
    assert cl.get(f"/api/deviations/{_add()}/dump").status_code == 404


def test_shot_url_encoded(cl, tmp_path):
    _files(tmp_path, {"a b#c.jpg": b"j"})
    j = cl.get(f"/api/deviations/{_add(shot='a b#c.jpg')}/shot").json()
    assert j["url"] == "/api/jobs/j1/artifacts/a%20b%23c.jpg"


def test_shot_separator_404(cl, tmp_path):
    _files(tmp_path, {"99_failure.jpg": b"j"})
    i = _add(shot="sub/../99_failure.jpg")
    assert cl.get(f"/api/deviations/{i}/shot").status_code == 404


def test_shot_job_dotdot_404(cl, tmp_path):
    (tmp_path / "99_failure.jpg").write_bytes(b"j")
    assert cl.get(f"/api/deviations/{_add(job='..')}/shot").status_code == 404


def test_shot_alt_devices(cl, tmp_path):
    _files(tmp_path, {"99_failure.jpg": b"j"})
    i = _add()
    item = dv.deviations.get(i)
    item.devices = []
    assert "устройство" in api.deviation_shot(i)["alt"]
    item.devices = ["A", "B"]
    assert "A, B" in api.deviation_shot(i)["alt"]


def test_dump_garbage_xml_clean_error(cl, tmp_path):
    _dump_files(tmp_path)
    (tmp_path / "j1" / "failure_hierarchy.xml").write_text("не xml <<", "utf-8")
    r = cl.get(f"/api/deviations/{_add()}/dump")
    assert r.status_code in (404, 500) and isinstance(r.json()["detail"], str)


def test_dump_file_vanished_404(cl, tmp_path, monkeypatch):
    _dump_files(tmp_path)
    real_text, real_bytes = Path.read_text, Path.read_bytes

    def _text(self, *a, **k):
        if self.suffix == ".xml":
            raise OSError("gone")
        return real_text(self, *a, **k)

    def _bytes(self, *a, **k):
        if self.suffix == ".jpg":
            raise OSError("gone")
        return real_bytes(self, *a, **k)
    for patch in (("read_text", _text), ("read_bytes", _bytes)):
        with monkeypatch.context() as m:
            m.setattr(Path, *patch)
            r = cl.get(f"/api/deviations/{_add()}/dump")
        assert r.status_code == 404 and "пропал" in r.json()["detail"]


def test_collect_writes_size(monkeypatch, tmp_path):
    for n in ("save_screenshot", "dump_hierarchy", "logcat_tail", "current_app"):
        monkeypatch.setattr(control, n, lambda *a, **k: "")
    monkeypatch.setattr(control, "size", lambda s: (1080, 2400))
    monkeypatch.setattr(R.obstacle, "capture", lambda *a, **k: {})
    job = R.Job(id="j1", scenario_key="k", scenario_name="К", serial="s",
                device_name="D", params={})
    R._collect_failure_artifacts(job, tmp_path)
    assert json.loads((tmp_path / "failure_size.json").read_text()) == {
        "width": 1080, "height": 2400}
