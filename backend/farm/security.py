"""Защита локального API от чужих веб-страниц и (по желанию) от соседей по сети.

Ферма слушает 127.0.0.1, но этого мало: любая открытая в браузере страница
может слать запросы на http://localhost:8777. Два вектора закрываются здесь.

* CSRF. Чужой сайт отправляет POST (форма, fetch no-cors) — браузер его
  донесёт, просто не покажет ответ. Этого хватает, чтобы выполнить shell на
  телефонах или затереть аккаунты. Поэтому меняющие запросы принимаются,
  только если Origin (или Referer) совпадает с Host. Браузер всегда ставит
  Origin на кросс-доменный POST; curl и скрипты без Origin проходят.
* DNS rebinding. Домен злоумышленника перепривязывается на 127.0.0.1, и
  страница с «своего» адреса читает /api/accounts/{id}/password. Origin при
  этом совпадает с Host, но Host — чужое имя. Поэтому Host обязан быть
  IP-литералом, localhost или именем из FARM_ALLOWED_HOSTS.

FARM_TOKEN включает вход по секрету — нужен, если ферма открыта в сеть
(FARM_HOST=0.0.0.0): иначе любой в той же Wi-Fi видит пароли аккаунтов.
Токен один раз передаётся в ссылке /?token=..., дальше живёт в cookie.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOKEN_COOKIE = "farm_token"
TOKEN_HEADER = "x-farm-token"


def _env_hosts() -> set[str]:
    raw = os.getenv("FARM_ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def token() -> str:
    return os.getenv("FARM_TOKEN", "").strip()


def _split_host(value: str) -> str:
    """'Host'-заголовок без порта: '[::1]:8777' -> '::1', 'a.b:1' -> 'a.b'."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def host_allowed(host_header: str | None) -> bool:
    """IP-литерал, localhost или явно разрешённое имя. Пустой Host (HTTP/1.0,
    не браузер) пропускаем: DNS rebinding без Host не бывает."""
    if not host_header:
        return True
    name = _split_host(host_header)
    if name == "localhost" or name in _env_hosts():
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def origin_allowed(method: str, host_header: str | None,
                   origin: str | None, referer: str | None) -> bool:
    """Меняющий запрос — только со своей страницы."""
    if method.upper() in SAFE_METHODS:
        return True
    source = origin if origin is not None else referer
    if source is None:
        return True  # не браузер: curl, скрипты, тесты
    if source.strip().lower() == "null":
        return False  # sandbox-iframe, file://, data: — чужие по определению
    netloc = urlsplit(source).netloc.lower()
    return bool(netloc) and netloc == (host_header or "").strip().lower()


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _token_ok(request: Request, secret: str) -> bool:
    given = (request.headers.get(TOKEN_HEADER)
             or request.cookies.get(TOKEN_COOKIE) or "")
    return hmac.compare_digest(given.encode(), secret.encode())


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "same-origin",
}


async def guard(request: Request, call_next) -> Response:  # noqa: ANN001
    headers = request.headers
    host = headers.get("host")
    if not host_allowed(host):
        return PlainTextResponse(
            "недопустимый Host. Откройте ферму по http://127.0.0.1 или добавьте "
            "имя в FARM_ALLOWED_HOSTS", status_code=403)
    if not origin_allowed(request.method, host, headers.get("origin"), headers.get("referer")):
        return PlainTextResponse("запрос с чужой страницы отклонён", status_code=403)

    secret = token()
    if secret:
        given = request.query_params.get("token")
        if request.method == "GET" and request.url.path == "/" and given is not None:
            if not hmac.compare_digest(given.encode(), secret.encode()):
                return PlainTextResponse("неверный токен", status_code=401)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(TOKEN_COOKIE, secret, httponly=True, samesite="lax",
                            path="/", max_age=60 * 60 * 24 * 365)
            return resp
        if not _token_ok(request, secret):
            return PlainTextResponse(
                "нужен токен фермы: откройте /?token=<FARM_TOKEN>", status_code=401)

    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response
