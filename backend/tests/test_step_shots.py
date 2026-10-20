"""Снимки после шагов: только по желанию, у упавшего шага — свой кадр сбоя."""
from farm import config
from farm.devices import runner


def _job(tmp_path, monkeypatch, shots):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", str(tmp_path))
    job = runner.Job(id="j1", scenario_key="s", scenario_name="S", serial="X", device_name="P", params={},
                     step_shots=shots)
    (tmp_path / job.id).mkdir()
    job.step_total = 3
    return job


def test_step_shot_written_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.control, "screenshot", lambda serial, **kw: b"\xff\xd8jpeg")
    job = _job(tmp_path, monkeypatch, True)
    runner._open_step(job, 0, ["a", "b", "c"])
    runner._open_step(job, 1, ["a", "b", "c"])
    first = job.timeline[0]
    assert first["shot"] == "step_01.jpg"
    assert (tmp_path / "j1" / "step_01.jpg").read_bytes() == b"\xff\xd8jpeg"
    assert "shot" not in job.timeline[1]   # текущий шаг ещё идёт


def test_no_shots_by_default(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.control, "screenshot", lambda serial, **kw: calls.append(1) or b"x")
    job = _job(tmp_path, monkeypatch, False)
    runner._open_step(job, 0, ["a", "b"])
    runner._open_step(job, 1, ["a", "b"])
    assert not calls and "shot" not in job.timeline[0]


def test_shot_failure_does_not_break_run(tmp_path, monkeypatch):
    def boom(serial, **kw):
        raise RuntimeError("нет экрана")

    monkeypatch.setattr(runner.control, "screenshot", boom)
    job = _job(tmp_path, monkeypatch, True)
    runner._open_step(job, 0, ["a", "b"])
    runner._open_step(job, 1, ["a", "b"])
    assert "shot" not in job.timeline[0]
    assert any("снимок шага 1 не снят" in line for line in job.lines)
