"""Отчёт о запуске: чистая страница, слой резолвера в шагах, API."""
import json

import pytest
from fastapi import HTTPException

from farm import config, report
from farm.api import jobs as jobs_api
from farm.devices import runner as rn
from farm.resolve import Hit

PNG = (b"\x89PNG\r\n\x1a\n" + b"0" * 20)


def _rep(**kw):
    base = {"job": "abc123", "scenario": "Лайк <b>", "device": "Телефон 1", "status": "failed",
            "error": "цель не найдена <script>", "error_info": {"title": "Не нашли", "hint": "Обновите"},
            "app_version": {"name": "1.2.3", "code": 45, "package": "com.x"},
            "time_by_reason": {"ожидание": 3.5},
            "steps": [
                {"i": 0, "label": "Открыть <i>", "status": "ok", "secs": 1.0, "n": 2,
                 "layer": "template", "detail": "score 0.91", "degraded": True, "shot": "step_01.jpg"},
                {"i": 1, "label": "Нажать", "status": "failed", "secs": 2.5, "layer": "selector",
                 "degraded": False}]}
    base.update(kw)
    return base


def test_страница_самодостаточна_и_экранирована():
    out = report.render_html(_rep(), {"step_01.jpg": PNG})
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "&lt;b&gt;" in out and "&lt;i&gt;" in out
    assert "data:image/png;base64," in out
    assert "http://" not in out and "https://" not in out
    assert "score 0.91" in out and "по картинке" in out
    assert "1.2.3" in out and "ожидание" in out
    assert "1 из 2 шагов" in out


def test_без_кадров_и_версии_не_падает():
    out = report.render_html({"status": "passed", "steps": []}, {})
    assert "не определена" in out and "Шаги не записывались" in out


def test_слой_худший_побеждает(monkeypatch):
    job = rn.Job.__new__(rn.Job)
    job.timeline = [{"i": 0, "status": "ok"}]
    rn._note_layer(job, Hit(0.5, 0.5, "ocr", "x"))
    rn._note_layer(job, Hit(0.5, 0.5, "selector", ""))
    e = job.timeline[0]
    assert e["layer"] == "ocr" and e["degraded"] is True


@pytest.fixture
def tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARTIFACTS_DIR", tmp_path)
    return tmp_path


def test_api_отчёт_и_скачивание(tmp):
    (tmp / "abc123").mkdir()
    (tmp / "abc123" / "report.json").write_text(json.dumps(_rep()), "utf-8")
    (tmp / "abc123" / "step_01.jpg").write_bytes(PNG)
    r = jobs_api.job_report("abc123")
    assert "text/html" in r.media_type
    assert "content-disposition" not in r.headers
    assert b"base64" in r.body
    r = jobs_api.job_report("abc123", download=1)
    assert "attachment" in r.headers["content-disposition"]
    with pytest.raises(HTTPException) as e:
        jobs_api.job_report("ffffff")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        jobs_api.job_report("../x")
    assert e.value.status_code == 400


def test_api_отчёт_пачки(tmp, monkeypatch):
    for jid, st in (("aaaaaa", "passed"), ("bbbbbb", "failed")):
        (tmp / jid).mkdir()
        (tmp / jid / "report.json").write_text(json.dumps(_rep(status=st)), "utf-8")
    fake = [{"id": "aaaaaa", "device_name": "P1", "status": "passed", "scenario_name": "S"},
            {"id": "bbbbbb", "device_name": "P2", "status": "failed", "scenario_name": "S", "error": "e"}]
    monkeypatch.setattr(jobs_api.runner, "list_jobs", lambda **kw: fake)
    text = jobs_api.batch_report("xyz123").body.decode()
    assert "/api/jobs/aaaaaa/report.html" in text and "/api/jobs/bbbbbb/report.html" in text
    assert "P1" in text and "P2" in text
    monkeypatch.setattr(jobs_api.runner, "list_jobs", lambda **kw: [])
    with pytest.raises(HTTPException) as e:
        jobs_api.batch_report("xyz123")
    assert e.value.status_code == 404
