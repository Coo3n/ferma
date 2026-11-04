"""Ограничения одного процесса: HTTP flood, перебор, память и медленные тела.

Это защита приложения, не защита интернет-канала от объёмного DDoS.
Состояние ограничено по размеру; X-Forwarded-For не является источником IP.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import re
import time

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse


class RateLimiter:
    def __init__(self, rate: float, burst: int, max_keys: int = 4096, clock=time.monotonic):
        self.rate, self.burst, self.max_keys, self.clock = rate, burst, max_keys, clock
        self.entries: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def allow(self, key: str) -> bool:
        now = self.clock()
        while self.entries and now - next(iter(self.entries.values()))[1] > 300:
            self.entries.popitem(last=False)
        previous = self.entries.pop(key, None)
        if previous is None:
            if len(self.entries) >= self.max_keys:
                return False
            tokens = float(self.burst)
        else:
            tokens = min(self.burst, previous[0] + (now - previous[1]) * self.rate)
        allowed = tokens >= 1
        self.entries[key] = (tokens - 1 if allowed else tokens, now)
        return allowed


def peer_key(scope: dict) -> str:
    return (scope.get("client") or ("unknown", 0))[0]


async def reject(scope, receive, send, status: int, message: str) -> None:
    from .security import protect_response
    headers = {"Retry-After": "1"} if status in (429, 503) else {}
    response = protect_response(Request(scope), PlainTextResponse(message, status, headers=headers))
    await response(scope, receive, send)


class TrafficLimits:
    """До авторизации: дешёвый rate limit и ограничение открытых HTTP запросов."""
    def __init__(self, app, rate=200, burst=400, max_active=256, max_peer_active=128):
        self.app = app
        self.peers = RateLimiter(rate, burst)
        self.global_rate = RateLimiter(400, 800, max_keys=1)
        self.writes = RateLimiter(30, 60)
        self.max_active, self.max_peer_active = max_active, max_peer_active
        self.active = 0
        self.active_peers: dict[str, int] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        peer = peer_key(scope)
        if (not self.global_rate.allow("all") or not self.peers.allow(peer)
                or (scope["method"] not in ("GET", "HEAD", "OPTIONS")
                    and not self.writes.allow(peer))):
            return await reject(scope, receive, send, 429, "Слишком много запросов. Подождите немного.")
        if self.active >= self.max_active or self.active_peers.get(peer, 0) >= self.max_peer_active:
            return await reject(scope, receive, send, 503, "Сервер занят. Повторите запрос позже.")
        self.active += 1
        self.active_peers[peer] = self.active_peers.get(peer, 0) + 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.active -= 1
            remaining = self.active_peers[peer] - 1
            if remaining:
                self.active_peers[peer] = remaining
            else:
                del self.active_peers[peer]


# Эти обработчики сами считают байты потока и удаляют временные файлы при ошибке.
STREAM_UPLOADS = {"/api/bulk/install", "/api/bulk/push", "/api/apks",
                  "/api/backup/inspect", "/api/backup/restore"}
FILE_UPLOAD = re.compile(r"/api/devices/[^/]+/fs/upload")


class BodyLimits:
    """После авторизации, до JSON-парсинга. APK остаются потоковыми на диск."""
    def __init__(self, app, max_bytes=32 * 1024 * 1024, timeout=30, max_readers=8):
        self.app, self.max_bytes, self.timeout = app, max_bytes, timeout
        self.max_readers, self.readers, self.uploads = max_readers, 0, 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        streaming = (scope["method"] == "POST" and
                     (scope["path"] in STREAM_UPLOADS or FILE_UPLOAD.fullmatch(scope["path"])))
        if streaming:
            if self.uploads >= 4:
                return await reject(scope, receive, send, 503, "Слишком много одновременных загрузок.")
            self.uploads += 1
            deadline = time.monotonic() + 1800
            async def timed_receive():
                try:
                    return await asyncio.wait_for(receive(), min(self.timeout, max(0, deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    raise HTTPException(408, "Истекло время загрузки.") from None
            try:
                await self.app(scope, timed_receive, send)
            finally:
                self.uploads -= 1
            return
        if self.readers >= self.max_readers:
            return await reject(scope, receive, send, 503, "Слишком много одновременных загрузок.")
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit() or len(lengths[0]) > 12:
                return await reject(scope, receive, send, 400, "Некорректный Content-Length.")
            if int(lengths[0]) > self.max_bytes:
                return await reject(scope, receive, send, 413, "Тело запроса слишком большое.")
        self.readers += 1
        body = bytearray()
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    message = await asyncio.wait_for(receive(), max(0, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    return await reject(scope, receive, send, 408, "Истекло время получения запроса.")
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.max_bytes:
                    return await reject(scope, receive, send, 413, "Тело запроса слишком большое.")
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            pending = True
            async def replay():
                nonlocal pending
                if pending:
                    pending = False
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()
            await self.app(scope, replay, send)
        finally:
            self.readers -= 1
