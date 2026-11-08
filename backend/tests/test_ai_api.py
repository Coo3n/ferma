"""ИИ-мастер: маршруты /api/ai. Сеть и телефон замоканы: client.chat/list_models
подменены, runner.submit/get/cancel — заглушки, сюжет — подмена saver.load_recipe."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from farm import config, versions
from farm.api import ai
from farm.vlm import client, probe, review, settings

STEPS = [{"kind": "launch_app", "args": {"package": "com.example.app"}},
         {"kind": "sleep", "args": {"seconds": 2}},
         {"kind": "key", "args": {"name": "back"}}]


class Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


class Shim:
    """starlette TestClient недоступен (нет httpx) — вызываем обработчики роутера напрямую."""

    def _call(self, method, url, body=None):
        path, _, qs = url.partition("?")
        query = dict(p.split("=") for p in qs.split("&") if p)
        for r in ai.router.routes:
            m = r.path_regex.match(path)
            if m and method in r.methods:
                kw = dict(m.groupdict(), **query)
                if body is not None and "payload" in r.endpoint.__code__.co_varnames[:r.endpoint.__code__.co_argcount]:
                    kw["payload"] = body
                try:
                    out = r.endpoint(**kw)
                except HTTPException as e:
                    return Resp(e.status_code, {"detail": e.detail})
                if isinstance(out, JSONResponse):
                    return Resp(out.status_code, json.loads(out.body))
                return Resp(200, out)
        raise AssertionError("no route " + url)

    def post(self, url, json=None):
        return self._call("POST", url, json if json is not None else {})

    def get(self, url):
        return self._call("GET", url)


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    ai._cache.clear()
    return Shim()


def _saved(monkeypatch, steps):
    monkeypatch.setattr(ai.saver, "load_recipe", lambda key: {"steps": steps} if key == "sc" else None)


def _fake_runner(monkeypatch, status="running"):
    job = SimpleNamespace(id="job1", status=status, step_index=1, step_total=3, timeline=[{"i": 0}],
                          error="", )
    cancelled = []
    monkeypatch.setattr(ai.runner, "submit", lambda key, serials, **kw: [job])
    monkeypatch.setattr(ai.runner, "get", lambda jid: job if jid == "job1" else None)
    monkeypatch.setattr(ai.runner, "job_dict", lambda j, **kw: {"id": j.id})
    monkeypatch.setattr(ai.runner, "cancel", lambda jid: cancelled.append(jid) or True)
    return job, cancelled


def test_finding_validation_binds_to_steps_and_drops_bad():
    good = {"id": "a", "steps": [1], "severity": "low", "title": "t", "why": "w", "basis": "analysis",
            "fix": {"op": "replace", "index": 1, "step": {"kind": "sleep", "args": {"seconds": 5}}}}
    bad = [dict(good, steps=[9]), dict(good, steps=[]), dict(good, severity="x"),
           dict(good, fix={"op": "replace", "index": 1, "step": {"kind": "nope", "args": {}}}),
           dict(good, fix={"op": "insert", "index": 99, "step": good["fix"]["step"]}), "junk"]
    out, dropped = review.validate_findings([good] + bad, STEPS)
    assert [f["id"] for f in out] == ["a"] and dropped == len(bad)
    assert out[0]["fix"]["step"]["args"]["seconds"] == 5.0
    ins = dict(good, fix={"op": "insert", "index": 3, "step": good["fix"]["step"]})
    assert review.validate_findings([ins], STEPS)[0]


def test_review_route_parses_strictly_and_is_idempotent(api, monkeypatch):
    calls = []
    reply = json.dumps({"findings": [
        {"steps": [0], "severity": "med", "title": "t", "why": "w", "basis": "assumption", "fix": None},
        {"steps": [7], "severity": "med", "title": "t", "why": "w", "basis": "assumption", "fix": None}]})
    monkeypatch.setattr(client, "chat", lambda *a, **k: calls.append(1) or reply)
    body = {"steps": STEPS, "request_id": "r1"}
    r = api.post("/api/ai/review", json=body).json()
    assert len(r["findings"]) == 1 and r["dropped"] == 1 and r["request_id"] == "r1"
    assert r["version"] == versions.version_of(ai._steps(STEPS))
    api.post("/api/ai/review", json=body)
    assert len(calls) == 1
    monkeypatch.setattr(client, "chat", lambda *a, **k: '{"findings": [{"steps": ')
    assert api.post("/api/ai/review", json={"steps": STEPS, "request_id": "r2"}).status_code == 502


def test_versions_idempotent_and_listing(api):
    a = api.post("/api/ai/versions", json={"scenario_key": "sc", "steps": STEPS, "label": "v1"}).json()
    b = api.post("/api/ai/versions", json={"scenario_key": "sc", "steps": STEPS}).json()
    assert a["created"] and not b["created"] and a["version"] == b["version"]
    lst = api.get("/api/ai/versions/sc").json()
    assert len(lst) == 1 and lst[0]["steps_count"] == 3 and lst[0]["label"] == "v1"
    assert api.get(f"/api/ai/versions/sc/{a['version']}").json()["steps"][0]["kind"] == "launch_app"
    assert api.get("/api/ai/versions/sc/nope").status_code == 404


def test_run_checks_version_then_runs_and_is_current_resets(api, monkeypatch):
    _saved(monkeypatch, STEPS)
    job, cancelled = _fake_runner(monkeypatch)
    ver = versions.version_of(ai._steps(STEPS))
    assert api.post("/api/ai/run", json={"scenario_key": "sc", "version": "bad", "serial": "S"}).status_code == 409
    r = api.post("/api/ai/run", json={"scenario_key": "sc", "version": ver, "serial": "S"}).json()
    assert r["job_id"] == "job1"
    rows = api.get("/api/ai/runs?scenario_key=sc").json()
    assert rows[0]["is_current"] and rows[0]["status"] == "running" and rows[0]["step_total"] == 3
    assert versions.get_steps("sc", ver)               # снимок снят сервером
    assert (config.DATA_DIR / "ai_runs.json").is_file()
    # сюжет изменён -> прежний запуск уже не текущий
    _saved(monkeypatch, STEPS + [{"kind": "key", "args": {"name": "home"}}])
    assert api.get("/api/ai/runs?scenario_key=sc").json()[0]["is_current"] is False
    # stop и офлайн
    monkeypatch.setattr(ai.registry, "get", lambda s: SimpleNamespace(online=False))
    d = api.get(f"/api/ai/runs/{r['run_id']}").json()
    assert d["phone_state"] == "offline" and d["timeline"] == [{"i": 0}]
    assert api.post(f"/api/ai/runs/{r['run_id']}/stop").json()["ok"] and cancelled == ["job1"]
    assert api.get("/api/ai/runs/zzz").status_code == 404


def test_run_risky_requires_confirm(api, monkeypatch):
    risky = STEPS + [{"kind": "type", "args": {"value": "мой пароль 1234"}}]
    _saved(monkeypatch, risky)
    _fake_runner(monkeypatch)
    ver = versions.version_of(ai._steps(risky))
    body = {"scenario_key": "sc", "version": ver, "serial": "S"}
    r = api.post("/api/ai/run", json=body)
    assert r.status_code == 409 and r.json()["risky"][0]["index"] == 3
    assert api.post("/api/ai/run", json={**body, "confirm_risky": True}).status_code == 200


def test_analyze_uses_screenshots_only_with_vision(api, monkeypatch):
    _saved(monkeypatch, STEPS)
    _fake_runner(monkeypatch)
    ver = versions.version_of(ai._steps(STEPS))
    run = api.post("/api/ai/run", json={"scenario_key": "sc", "version": ver, "serial": "S"}).json()
    import farm.api.jobs as jobs
    monkeypatch.setattr(jobs, "load_report", lambda *a, **k: {"steps": [{"i": 0, "label": "x", "status": "ok"}]})
    monkeypatch.setattr(jobs, "load_shots", lambda *a, **k: {"a.jpg": b"img"})
    seen = []
    reply = json.dumps({"observations": [{"text": "Экран настроек открылся", "basis": "confirmed"},
                                         {"text": "Возможно, приложение зависло", "basis": "wild"},
                                         {"text": "..", "basis": "confirmed"}],
                        "suggestions": []})
    monkeypatch.setattr(client, "chat", lambda m, cfg=None, images=None, **k: seen.append(images) or reply)
    r = api.post("/api/ai/analyze", json={"run_id": run["run_id"], "request_id": "a"}).json()
    assert r["vision_used"] is False and r["note"] and seen[-1] is None
    assert [o["basis"] for o in r["observations"]] == ["confirmed", "unverified"]
    settings.save({"url": "http://x/v1", "vision": "yes"})
    r = api.post("/api/ai/analyze", json={"run_id": run["run_id"], "request_id": "b"}).json()
    assert r["vision_used"] is True and seen[-1] == [b"img"] and r["version"] == ver


def test_draft_text_only_drops_coordinates(api, monkeypatch):
    settings.save({"url": "http://x/v1"})
    reply = json.dumps({"steps": [{"kind": "launch_app", "args": {"package": "com.a.b"}},
                                  {"kind": "tap", "args": {"x": 0.5, "y": 0.5}},
                                  {"kind": "click", "args": {"text": "Войти"}}], "notes": []})
    monkeypatch.setattr(client, "chat", lambda *a, **k: reply)
    r = api.post("/api/ai/draft", json={"task": "открой приложение", "serial": "S"}).json()
    assert r["status"] == "steps" and r["needs_screen"] is True
    assert [s["kind"] for s in r["steps"]] == ["launch_app", "click"] and r["version"]
    monkeypatch.setattr(client, "chat", lambda *a, **k: '{"questions": ["Какое приложение?"]}')
    assert api.post("/api/ai/draft", json={"task": "сделай"}).json() == {
        "status": "questions", "questions": ["Какое приложение?"]}


def test_probe_vision_states_and_reset(api, monkeypatch):
    settings.save({"url": "http://x/v1", "model": "m", "key": "SECRET"})

    def fake(msgs, cfg=None, images=None, **k):
        return "red" if images else "OK"
    monkeypatch.setattr(client, "chat", fake)
    r = api.post("/api/ai/probe", json={}).json()
    assert r["reachable"] and r["text_ok"] and r["vision"] == "yes"
    assert settings.get().vision == "yes" and "SECRET" not in json.dumps(r)
    settings.save({"model": "other"})
    assert settings.get().vision == "unknown"          # сброс при смене модели

    def reject(msgs, cfg=None, images=None, **k):
        if images:
            e = client.VlmError("нейросеть ответила ошибкой 400")
            e.status = 400
            raise e
        return "OK"
    monkeypatch.setattr(client, "chat", reject)
    assert api.post("/api/ai/probe", json={}).json()["vision"] == "no"
    monkeypatch.setattr(client, "chat", lambda m, cfg=None, images=None, **k: "green" if images else "OK")
    assert api.post("/api/ai/probe", json={}).json()["vision"] == "no"

    def down(*a, **k):
        raise client.VlmError("нейросеть недоступна: по этому адресу никто не отвечает")
    monkeypatch.setattr(client, "chat", down)
    r = api.post("/api/ai/probe", json={}).json()
    assert r["reachable"] is False and r["vision"] == "unknown"


def test_models_does_not_send_saved_key_to_other_url(api, monkeypatch):
    settings.save({"url": "http://saved/v1", "key": "SECRET"})
    keys = []
    monkeypatch.setattr(client, "list_models", lambda cfg: keys.append((cfg.url, cfg.key)) or [{"id": "m1"}])
    r = api.post("/api/ai/models", json={"url": "http://saved/v1"}).json()
    assert r == {"models": [{"id": "m1"}]}
    api.post("/api/ai/models", json={"url": "http://other/v1"})
    api.post("/api/ai/models", json={"url": "http://other/v1", "key": "NEW"})
    assert keys == [("http://saved/v1", "SECRET"), ("http://other/v1", ""), ("http://other/v1", "NEW")]

    def boom(cfg):
        raise client.VlmError("нейросеть ответила ошибкой 401")
    monkeypatch.setattr(client, "list_models", boom)
    out = api.post("/api/ai/models", json={"url": "http://saved/v1"}).json()
    assert out["models"] == [] and "401" in out["error"] and "SECRET" not in json.dumps(out)


def test_client_chat_builds_request(monkeypatch):
    seen = {}

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices":[{"message":{"content":"hi"}}]}'

    def fake(req, timeout):
        seen["body"] = json.loads(req.data)
        seen["auth"] = req.headers.get("Authorization")
        return R()
    monkeypatch.setattr(client.urllib.request, "urlopen", fake)
    cfg = settings.Settings(url="http://x/v1", model="m", key="K")
    assert client.chat([{"role": "user", "content": "q"}], cfg, images=[b"notimage"]) == "hi"
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image_url" and content[1]["text"] == "q" and seen["auth"] == "Bearer K"
