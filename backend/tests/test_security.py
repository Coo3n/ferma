"""Аудит безопасности: Host/Origin/токен, аккаунты 600, загрузки, кавычки в shell."""
import asyncio
import json
import logging
import os
import stat
from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from farm import accounts, adb, security
from farm.api import accounts as accounts_api
from farm.api import bulk
from farm.api import jobs as jobs_api
from farm.control import apps, input as finput


# ------------------------------------------------------------ Host / Origin

@pytest.mark.parametrize("host", [
    None, "", "localhost", "localhost:8777", "127.0.0.1:8777", "[::1]:8777",
    "192.168.1.5:8777", "10.0.0.2",
])
def test_host_allowed(host):
    assert security.host_allowed(host)


@pytest.mark.parametrize("host", [
    "evil.com", "evil.com:8777", "127.0.0.1.nip.io:8777", "localhost.evil.com",
])
def test_host_rejected_dns_rebinding(host):
    assert not security.host_allowed(host)


def test_allowed_hosts_env(monkeypatch):
    monkeypatch.setenv("FARM_ALLOWED_HOSTS", "farm.lan, other.lan")
    assert security.host_allowed("farm.lan:8777")
    assert not security.host_allowed("evil.lan")


@pytest.mark.parametrize("method,origin,referer,ok", [
    ("GET", "http://evil.com", None, True),          # чтение ответа и так закрыто SOP
    ("POST", "http://127.0.0.1:8777", None, True),
    ("POST", None, None, True),                       # curl / скрипт
    ("POST", "http://evil.com", None, False),
    ("POST", "null", None, False),
    ("DELETE", "http://localhost:8777", None, False),  # другое имя — другой origin
    ("PATCH", None, "http://evil.com/x", False),
    ("POST", None, "http://127.0.0.1:8777/#acc", True),
])
def test_origin_allowed(method, origin, referer, ok):
    assert security.origin_allowed(method, "127.0.0.1:8777", origin, referer) is ok


def _request(method="GET", path="/api/status", headers=None, query=b"", scheme="http"):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": method, "path": path, "headers": raw,
                    "query_string": query, "scheme": scheme, "server": ("127.0.0.1", 8777)})


def _guard(req):
    async def call_next(_):
        return PlainTextResponse("ok")
    return asyncio.run(security.guard(req, call_next))


def test_guard_blocks_rebinding_and_csrf(monkeypatch):
    monkeypatch.delenv("FARM_TOKEN", raising=False)
    assert _guard(_request(headers={"host": "evil.com:8777"})).status_code == 403
    assert _guard(_request("POST", "/api/run", {"host": "127.0.0.1:8777",
                                                "origin": "http://evil.com"})).status_code == 403
    ok = _guard(_request("POST", "/api/run", {"host": "127.0.0.1:8777",
                                              "origin": "http://127.0.0.1:8777"}))
    assert ok.status_code == 200
    assert ok.headers["x-frame-options"] == "DENY"
    assert ok.headers["x-content-type-options"] == "nosniff"


def test_guard_token(monkeypatch):
    monkeypatch.setenv("FARM_TOKEN", "s3cret")
    h = {"host": "192.168.1.5:8777"}
    assert _guard(_request(headers=h)).status_code == 401
    assert _guard(_request(path="/", headers=h, query=b"token=bad")).status_code == 401
    login = _guard(_request(path="/", headers=h, query=b"token=s3cret"))
    assert login.status_code == 303
    cookie = login.headers["set-cookie"]
    assert "farm_token=s3cret" in cookie and "httponly" in cookie.lower()
    assert _guard(_request(headers={**h, "cookie": "farm_token=s3cret"})).status_code == 200
    assert _guard(_request(headers={**h, "x-farm-token": "s3cret"})).status_code == 200
    assert _guard(_request(headers={**h, "cookie": "farm_token=nope"})).status_code == 401


def test_loopback_detection():
    assert security.is_loopback("127.0.0.1") and security.is_loopback("localhost")
    assert not security.is_loopback("0.0.0.0")


def test_app_has_guard():
    from farm import server
    names = [getattr(m, "kwargs", {}).get("dispatch") for m in server.app.user_middleware]
    assert security.guard in names


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:8777", "https://[broken", "https://127.0.0.1:bad",
    "https://user@127.0.0.1:8777", "https://127.0.0.1:8777/path",
])
def test_https_rejects_downgraded_or_malformed_origin(monkeypatch, origin):
    monkeypatch.delenv("FARM_TOKEN", raising=False)
    response = _guard(_request("POST", headers={
        "host": "127.0.0.1:8777", "origin": origin,
    }, scheme="https"))
    assert response.status_code == 403


def test_https_accepts_same_origin_default_port(monkeypatch):
    monkeypatch.delenv("FARM_TOKEN", raising=False)
    response = _guard(_request("POST", headers={
        "host": "localhost:443", "origin": "https://localhost",
    }, scheme="https"))
    assert response.status_code == 200


def test_https_login_cookie_and_auth_responses_are_private(monkeypatch):
    monkeypatch.setenv("FARM_TOKEN", "s3cret")
    response = _guard(_request(path="/", headers={"host": "localhost:8777"},
                              query=b"token=s3cret", scheme="https"))
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "max-age=43200" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("secret,scheme,expected", [
    ("", "https", 503), ("short", "https", 503),
    ("a" * 32, "http", 403), ("a" * 32, "https", 200),
])
def test_remote_access_fails_closed(monkeypatch, secret, scheme, expected):
    from farm import config
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    monkeypatch.setenv("FARM_TOKEN", secret)
    monkeypatch.setenv("FARM_HTTPS", "1")
    response = _guard(_request(headers={"host": "192.168.1.2:8777",
                                        "x-farm-token": secret,
                                        "x-forwarded-proto": "https"}, scheme=scheme))
    assert response.status_code == expected


@pytest.mark.parametrize("host,secret,query", [
    ("evil.com", "", b""), ("localhost", "secret", b""),
    ("localhost", "secret", b"token=wrong"), ("localhost", "", b""),
])
def test_security_headers_cover_denials_and_api(monkeypatch, host, secret, query):
    monkeypatch.setenv("FARM_TOKEN", secret)
    response = _guard(_request(headers={"host": host}, query=query, scheme="https"))
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "object-src 'none'" in response.headers["content-security-policy"]
    assert "max-age=" in response.headers["strict-transport-security"]


def test_security_preserves_artifact_sandbox(monkeypatch):
    monkeypatch.delenv("FARM_TOKEN", raising=False)
    async def handler(_):
        return PlainTextResponse("artifact", headers={"Content-Security-Policy": "sandbox"})
    response = asyncio.run(security.guard(_request(headers={"host": "localhost"}), handler))
    assert response.headers["content-security-policy"] == "sandbox"


def test_unhandled_error_does_not_disclose_exception():
    from farm import server
    handler = server.create_app().exception_handlers[Exception]
    response = asyncio.run(handler(_request(), RuntimeError("secret/path/password")))
    assert response.status_code == 500
    assert b"secret/path/password" not in response.body
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("headers", [
    {"sec-fetch-site": "cross-site"}, {"origin": "https://evil.test"},
    {"referer": "https://evil.test/page"},
])
def test_cross_site_get_cannot_trigger_device_recording(monkeypatch, headers):
    monkeypatch.delenv("FARM_TOKEN", raising=False)
    response = _guard(_request(path="/api/devices/TEST/record",
                              headers={"host": "localhost", **headers}, scheme="https"))
    assert response.status_code == 403


@pytest.mark.parametrize("path,cdn", [("/", False), ("/api/status", False),
                                      ("/docs", True), ("/redoc", True)])
def test_docs_assets_allowed_without_relaxing_application_csp(path, cdn):
    from starlette.responses import HTMLResponse
    response = security.protect_response(_request(path=path), HTMLResponse("docs"))
    policy = response.headers["content-security-policy"]
    assert ("https://cdn.jsdelivr.net" in policy) is cdn
    assert "object-src 'none'" in policy and "frame-ancestors 'none'" in policy


# ------------------------------------------------------------ аккаунты

@pytest.fixture
def acc_file(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    monkeypatch.setattr(accounts, "ACCOUNTS_FILE", path)
    monkeypatch.setattr(accounts, "_items", None)
    return path


def test_accounts_file_is_0600(acc_file):
    accounts.create({"platform": "vk", "login": "a", "password": "p@ss"})
    assert stat.S_IMODE(acc_file.stat().st_mode) == 0o600
    assert json.loads(acc_file.read_text("utf-8"))[0]["password"] == "p@ss"


def test_accounts_existing_644_tightened_on_load(acc_file):
    acc_file.write_text("[]", "utf-8")
    os.chmod(acc_file, 0o644)
    accounts.all_accounts()
    assert stat.S_IMODE(acc_file.stat().st_mode) == 0o600


def test_accounts_broken_file_is_backed_up_not_overwritten(acc_file):
    acc_file.write_text("{not json", "utf-8")
    accounts.create({"platform": "vk", "login": "a"})
    backups = list(acc_file.parent.glob("accounts.json.broken-*"))
    assert len(backups) == 1 and backups[0].read_text("utf-8") == "{not json"


def test_accounts_save_error_does_not_log_contents(acc_file, monkeypatch, caplog):
    accounts.create({"platform": "vk", "login": "a", "password": "TOPSECRET"})

    def boom(*a, **k):
        raise OSError("disk full TOPSECRET")
    monkeypatch.setattr(accounts.os, "replace", boom)
    with caplog.at_level(logging.WARNING, logger="farm.accounts"):
        with pytest.raises(accounts.SaveError):
            accounts.update(accounts.all_accounts()[0]["id"], {"note": "x"})
    assert "TOPSECRET" not in caplog.text
    assert not list(acc_file.parent.glob("*.tmp"))


def test_password_endpoint_not_cached(acc_file):
    item = accounts.create({"platform": "vk", "login": "a", "password": "pw"})
    resp = accounts_api.account_password(item["id"])
    assert resp.headers["cache-control"] == "no-store"
    assert json.loads(resp.body) == {"password": "pw"}
    assert "password" not in accounts_api.list_accounts()[0]


# ------------------------------------------------------------ загрузки

@pytest.mark.parametrize("name,expected", [
    ("app.apk", "app.apk"),
    ("../../etc/passwd", "passwd"),
    ("..\\..\\win.ini", "win.ini"),
    ("a b;reboot$(id)`x`.jpg", "a_b_reboot_id_x_.jpg"),
    ("фото.jpg", "фото.jpg"),
    ("..", "file"),
    ("", "file"),
])
def test_safe_name(name, expected):
    assert bulk.safe_name(name) == expected


class _FakeReq:
    def __init__(self, chunks, length=None):
        self._chunks = chunks
        self.headers = {"content-length": str(length)} if length is not None else {}

    async def stream(self):
        for c in self._chunks:
            yield c


def test_upload_streams_to_disk_and_cleans_dir():
    path = asyncio.run(bulk._upload(_FakeReq([b"ab", b"cd"]), "../x.apk"))
    assert path.name == "x.apk" and path.read_bytes() == b"abcd"
    bulk._discard(path)
    assert not path.parent.exists()


def test_upload_size_limit(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(bulk, "MAX_UPLOAD_BYTES", 3)
    with pytest.raises(HTTPException) as e:
        asyncio.run(bulk._upload(_FakeReq([b"ab"], length=10), "a.apk"))
    assert e.value.status_code == 413
    created = []
    real = bulk.tempfile.mkdtemp
    monkeypatch.setattr(bulk.tempfile, "mkdtemp",
                        lambda **k: created.append(real(**k)) or created[-1])
    with pytest.raises(HTTPException) as e:
        asyncio.run(bulk._upload(_FakeReq([b"ab", b"cd"]), "a.apk"))
    assert e.value.status_code == 413
    assert created and not Path(created[0]).exists()


def test_upload_empty_rejected():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(bulk._upload(_FakeReq([]), "a.apk"))
    assert e.value.status_code == 400


# ------------------------------------------------------------ shell телефона

@pytest.fixture
def shell_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(finput, "via_u2", lambda *a, **k: False)
    monkeypatch.setattr(apps, "via_u2", lambda *a, **k: False)
    monkeypatch.setattr(adb, "shell", lambda serial, cmd, timeout=None: calls.append(cmd) or "")
    return calls


def test_text_is_quoted_for_device_shell(shell_calls):
    finput.text("S", "p&ss;w$rd it's")
    assert shell_calls == [["input", "text", "'p&ss;w$rd%sit'\"'\"'s'"]]


def test_plain_text_unchanged(shell_calls):
    finput.text("S", "hello world")
    assert shell_calls == [["input", "text", "hello%sworld"]]


def test_text_error_redacts_value(monkeypatch):
    monkeypatch.setattr(finput, "via_u2", lambda *a, **k: False)

    def fail(serial, cmd, timeout=None):
        raise adb.AdbError(f"adb -s S shell {' '.join(cmd)} -> rc=1: boom")
    monkeypatch.setattr(adb, "shell", fail)
    with pytest.raises(adb.AdbError) as e:
        finput.text("S", "Sup3r&Secret")
    assert "Sup3r" not in str(e.value) and "***" in str(e.value)


def test_open_url_and_component_quoted(shell_calls):
    apps.open_url("S", "https://x.com/?a=1&b=2;reboot")
    apps.launch_app("S", "com.app", ".Main$Inner")
    assert shell_calls[0][-1] == "'https://x.com/?a=1&b=2;reboot'"
    assert shell_calls[1][-1] == "'com.app/.Main$Inner'"


def test_unsafe_serials_skipped(monkeypatch):
    out = ("List of devices attached\n"
           "R58M123 device model:SM_A50\n"
           "adb-R58-abc._adb-tls-connect._tcp device\n"
           "192.168.1.5:5555 device\n"
           "x'onmouseover=alert(1)' device\n"
           "a<b> device\n")
    monkeypatch.setattr(adb, "raw", lambda *a, **k: out)
    assert [d.serial for d in adb.list_devices()] == [
        "R58M123", "adb-R58-abc._adb-tls-connect._tcp", "192.168.1.5:5555"]


def test_artifact_served_sandboxed(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_api.config, "ARTIFACTS_DIR", tmp_path)
    (tmp_path / "abc123").mkdir()
    (tmp_path / "abc123" / "failure_hierarchy.xml").write_text("<x/>")
    resp = jobs_api.artifact("abc123", "failure_hierarchy.xml")
    assert resp.headers["content-security-policy"] == "sandbox"
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        jobs_api.artifact("abc123", "../../etc/passwd")
