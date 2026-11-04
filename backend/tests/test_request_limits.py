"""Attack regressions use ASGI messages, including chunked/slow request bodies."""
import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import PlainTextResponse


async def invoke(app, *, chunks=(), headers=(), path="/api/example", method="POST", peer="127.0.0.1"):
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": method, "path": path,
             "raw_path": path.encode(), "scheme": "https", "query_string": b"",
             "headers": [(b"host", b"localhost"), *headers], "client": (peer, 1234),
             "server": ("127.0.0.1", 443)}
    pending = list(chunks) or [b""]
    messages = []
    async def receive():
        if pending:
            return {"type": "http.request", "body": pending.pop(0), "more_body": bool(pending)}
        return {"type": "http.disconnect"}
    async def send(message):
        messages.append(message)
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    return start["status"], dict(start["headers"]), b"".join(m.get("body", b"") for m in messages)


async def echo(scope, receive, send):
    body = await Request(scope, receive).body()
    await PlainTextResponse(body or b"ok")(scope, receive, send)


def test_bucket_recovers_and_bounds_memory():
    from farm.limits import RateLimiter
    now = [0.0]
    limiter = RateLimiter(rate=1, burst=2, max_keys=2, clock=lambda: now[0])
    assert limiter.allow("one") and limiter.allow("one")
    assert not limiter.allow("one")
    now[0] += 1
    assert limiter.allow("one")
    assert limiter.allow("two")
    assert not limiter.allow("three")  # cannot allocate unbounded attacker-controlled keys
    now[0] += 301
    assert limiter.allow("three")


def test_http_flood_is_limited_despite_forwarding_headers():
    from farm.limits import TrafficLimits
    app = TrafficLimits(echo, rate=0.001, burst=2)
    async def scenario():
        assert (await invoke(app))[0] == 200
        assert (await invoke(app, headers=[(b"x-forwarded-for", b"10.0.0.1")]))[0] == 200
        status, headers, _ = await invoke(app, headers=[(b"x-forwarded-for", b"10.0.0.2")])
        assert status == 429 and b"retry-after" in headers
        assert headers[b"cache-control"] == b"no-store"
    asyncio.run(scenario())


def test_concurrency_limit_releases_slot_after_disconnect():
    from farm.limits import TrafficLimits
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow(scope, receive, send):
            entered.set()
            await release.wait()
            await echo(scope, receive, send)
        app = TrafficLimits(slow, max_active=1)
        first = asyncio.create_task(invoke(app))
        await entered.wait()
        assert (await invoke(app))[0] == 503
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert (await invoke(app))[0] == 200
    asyncio.run(scenario())


@pytest.mark.parametrize("chunks,headers", [
    ([b"12345"], []), ([b"12", b"345"], []),
    ([b"12", b"345"], [(b"content-length", b"2")]),
    ([], [(b"content-length", b"9999999")]),
])
def test_body_limit_precedes_handler_even_for_chunked(chunks, headers):
    from farm.limits import BodyLimits
    async def forbidden(*args):
        pytest.fail("oversized request reached application")
    status, _, _ = asyncio.run(invoke(BodyLimits(forbidden, max_bytes=4),
                                     chunks=chunks, headers=headers))
    assert status == 413


def test_body_at_limit_is_replayed_without_corruption():
    from farm.limits import BodyLimits
    status, _, body = asyncio.run(invoke(BodyLimits(echo, max_bytes=4), chunks=[b"12", b"34"]))
    assert status == 200 and body == b"1234"


def test_slow_body_times_out_before_handler():
    from farm.limits import BodyLimits
    async def scenario():
        async def never():
            await asyncio.Event().wait()
        messages = []
        async def send(message):
            messages.append(message)
        async def forbidden(*args):
            pytest.fail("slow request reached handler")
        scope = {"type": "http", "method": "POST", "path": "/api/example", "scheme": "https",
                 "headers": [(b"host", b"localhost")], "query_string": b""}
        await BodyLimits(forbidden, timeout=0.01)(scope, never, send)
        assert messages[0]["status"] == 408
    asyncio.run(scenario())


def test_streaming_upload_remains_streaming():
    from farm.limits import BodyLimits
    # These handlers already enforce their own disk/ZIP size limits.
    status, _, body = asyncio.run(invoke(BodyLimits(echo, max_bytes=4),
                                        path="/api/bulk/install", chunks=[b"12", b"345"]))
    assert status == 200 and body == b"12345"


def test_token_bruteforce_is_throttled_but_valid_token_works(monkeypatch):
    from farm import security
    from farm.limits import RateLimiter
    monkeypatch.setenv("FARM_TOKEN", "correct-secret")
    monkeypatch.setattr(security, "LOGIN_LIMITER", RateLimiter(rate=0.001, burst=2))
    async def app(scope, receive, send):
        request = Request(scope, receive)
        async def next_handler(_):
            return PlainTextResponse("private")
        response = await security.guard(request, next_handler)
        await response(scope, receive, send)
    async def scenario():
        assert (await invoke(app))[0] == 401
        assert (await invoke(app))[0] == 401
        assert (await invoke(app))[0] == 429
        status, _, body = await invoke(app, headers=[(b"x-farm-token", b"correct-secret")])
        assert status == 200 and body == b"private"
    asyncio.run(scenario())


def test_full_stack_stalled_upload_returns_408_and_cleans_tempfiles(monkeypatch):
    from farm import config, server
    from farm.api import bulk
    from farm.limits import BodyLimits
    monkeypatch.setattr(config, "SERVE_FRONTEND", False)
    monkeypatch.delenv("FARM_TOKEN", raising=False)
    created = []
    real = bulk.tempfile.mkdtemp
    monkeypatch.setattr(bulk.tempfile, "mkdtemp", lambda **kw: created.append(real(**kw)) or created[-1])
    app = server.create_app()
    next(m for m in app.user_middleware if m.cls is BodyLimits).kwargs["timeout"] = 0.01
    # Supply one empty request marked more_body then stall; actual APK handler
    # creates a temporary directory before waiting for its first data chunk.
    async def scenario():
        from pathlib import Path
        for _ in range(5):  # also proves upload slots were released (cap is four)
            messages = []
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                     "http_version": "1.1", "method": "POST", "path": "/api/apks",
                     "raw_path": b"/api/apks", "scheme": "https", "query_string": b"",
                     "headers": [(b"host", b"localhost")], "client": ("127.0.0.1", 1234),
                     "server": ("127.0.0.1", 443)}
            async def receive():
                await asyncio.Event().wait()
            async def send(message):
                messages.append(message)
            await app(scope, receive, send)
            assert messages[0]["status"] == 408
        assert created and all(not Path(p).exists() for p in created)
    asyncio.run(scenario())
