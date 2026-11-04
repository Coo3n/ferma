"""TLS must fail closed, including alternate startup and broken certificates."""
import asyncio
import ssl
import os
import subprocess
import sys

import pytest

from farm import config, security


@pytest.fixture(autouse=True)
def isolated_tls(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HOST", "127.0.0.1")
    for name in ("FARM_HTTPS", "FARM_TLS_CERT", "FARM_TLS_KEY", "FARM_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_default_requires_certificate():
    from farm import tls
    with pytest.raises(ValueError, match="setup_https"):
        tls.uvicorn_options()


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", ""])
def test_plaintext_cannot_bind_to_network(monkeypatch, host):
    from farm import tls
    monkeypatch.setattr(config, "HOST", host)
    monkeypatch.setenv("FARM_HTTPS", "0")
    monkeypatch.setenv("FARM_TOKEN", "a" * 32)
    with pytest.raises(ValueError, match="HTTPS"):
        tls.uvicorn_options()


@pytest.mark.parametrize("value", ["", "false", "yes", "2"])
def test_invalid_https_flag_is_not_a_downgrade(monkeypatch, value):
    from farm import tls
    monkeypatch.setenv("FARM_HTTPS", value)
    with pytest.raises(ValueError, match="FARM_HTTPS"):
        tls.uvicorn_options()


def test_explicit_local_http_has_no_tls_or_proxy_trust(monkeypatch):
    from farm import tls
    monkeypatch.setenv("FARM_HTTPS", "0")
    options = tls.uvicorn_options()
    assert not options.get("ssl_certfile")
    assert options["proxy_headers"] is False
    assert options["access_log"] is False  # token links must not appear in access logs
    assert tls.browser_url() == "http://127.0.0.1:8777"


@pytest.mark.parametrize("field", ["FARM_TLS_CERT", "FARM_TLS_KEY"])
def test_partial_custom_pair_is_rejected(monkeypatch, tmp_path, field):
    from farm import tls
    monkeypatch.setenv(field, str(tmp_path / "cert.pem"))
    with pytest.raises(ValueError, match="FARM_TLS_CERT.*FARM_TLS_KEY"):
        tls.uvicorn_options()


def test_invalid_pem_is_rejected_before_start(monkeypatch, tmp_path):
    from farm import tls
    for variable, name in (("FARM_TLS_CERT", "cert.pem"), ("FARM_TLS_KEY", "key.pem")):
        file = tmp_path / name
        file.write_text("invalid pem")
        file.chmod(0o600)
        monkeypatch.setenv(variable, str(file))
    with pytest.raises(ValueError, match="сертификат"):
        tls.uvicorn_options()


@pytest.mark.parametrize("host,url", [
    ("::1", "https://[::1]:8777"), ("::", "https://[::1]:8777"),
    ("0.0.0.0", "https://127.0.0.1:8777"), ("localhost", "https://localhost:8777"),
])
def test_browser_url_is_connectable(monkeypatch, host, url):
    from farm import tls
    monkeypatch.setattr(config, "HOST", host)
    assert tls.browser_url() == url


def test_remote_configuration_rejected_before_workers(monkeypatch):
    from farm import server
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    async def start():
        async with server.lifespan(server.app):
            pytest.fail("insecure startup was accepted")
    with pytest.raises(ValueError, match="FARM_TOKEN"):
        asyncio.run(start())


def test_alternate_asgi_launcher_cannot_bypass_remote_auth(monkeypatch):
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    request = Request({"type": "http", "method": "GET", "path": "/api/status",
                       "scheme": "https", "query_string": b"",
                       "headers": [(b"host", b"192.168.1.5")],
                       "client": ("192.168.1.6", 5555), "server": ("0.0.0.0", 8777)})
    async def next_handler(_):
        return PlainTextResponse("private data")
    response = asyncio.run(security.guard(request, next_handler))
    assert response.status_code == 503
    assert b"private data" not in response.body


def test_relative_data_dir_is_consistent_across_launcher_workdirs(tmp_path):
    env = {**os.environ, "FARM_DATA_DIR": os.path.relpath(tmp_path, config.PROJECT_DIR),
           "PYTHONPATH": str(config.ROOT)}
    script = "from farm import config; print(config.DATA_DIR.resolve())"
    for cwd in (config.PROJECT_DIR, config.ROOT):
        result = subprocess.check_output([sys.executable, "-c", script], env=env, cwd=cwd, text=True)
        assert result.strip() == str(tmp_path.resolve())


def test_slow_headers_close_connection_and_preserve_complete_requests(monkeypatch):
    import uvicorn
    from uvicorn.server import ServerState
    from farm import tls
    monkeypatch.setenv("FARM_HTTPS", "0")
    async def app(scope, receive, send):
        from starlette.responses import PlainTextResponse
        await PlainTextResponse("ok")(scope, receive, send)
    async def scenario():
        options = tls.uvicorn_options()
        options.pop("host"); options.pop("port")
        cfg = uvicorn.Config(app, lifespan="off", **options)
        cfg.load()
        protocol = cfg.http_protocol_class
        monkeypatch.setattr(protocol, "HEADER_TIMEOUT", 0.03, raising=False)
        state = ServerState()
        loop = asyncio.get_running_loop()
        listener = await loop.create_server(lambda: protocol(cfg, state, {}, _loop=loop), "127.0.0.1", 0)
        port = listener.sockets[0].getsockname()[1]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")
            await writer.drain()
            assert await asyncio.wait_for(reader.read(), 0.5) == b""
            writer.close(); await writer.wait_closed()
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            assert b"200 OK" in await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 0.5)
            assert await reader.readexactly(2) == b"ok"
            writer.write(b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Slow: ")
            await writer.drain()
            assert await asyncio.wait_for(reader.read(), 0.5) == b""
            writer.close(); await writer.wait_closed()
        finally:
            listener.close(); await listener.wait_closed()
            for connection in list(state.connections):
                connection.transport.close()
    asyncio.run(scenario())
