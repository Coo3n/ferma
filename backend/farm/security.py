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

from . import config
from .limits import RateLimiter, peer_key

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
TOKEN_COOKIE = "farm_token"
TOKEN_HEADER = "x-farm-token"
LOGIN_LIMITER = RateLimiter(rate=1 / 6, burst=10)


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
                   origin: str | None, referer: str | None, scheme: str = "http") -> bool:
    """Меняющий запрос — только со своей страницы."""
    if method.upper() in SAFE_METHODS:
        return True
    source = origin if origin is not None else referer
    if source is None:
        return True  # не браузер: curl, скрипты, тесты
    if source.strip().lower() == "null":
        return False  # sandbox-iframe, file://, data: — чужие по определению
    try:
        parsed = urlsplit(source)
        target = urlsplit(f"{scheme}://{host_header or ''}")
        if parsed.scheme not in ("http", "https") or parsed.username is not None:
            return False
        if origin is not None and (parsed.path or parsed.query or parsed.fragment):
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target_port = target.port or (443 if scheme == "https" else 80)
        return (bool(parsed.hostname) and parsed.scheme == scheme
                and parsed.hostname == target.hostname and port == target_port)
    except ValueError:
        return False


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_network(remote: bool | None = None) -> None:
    """Ошибочная конфигурация не должна открывать управление телефонами."""
    if remote is None:
        remote = not is_loopback(config.HOST)
    if remote:
        if os.getenv("FARM_HTTPS", "1") != "1":
            raise ValueError("Доступ по сети требует HTTPS (FARM_HTTPS=1).")
        if len(token()) < 32:
            raise ValueError("Доступ по сети требует FARM_TOKEN длиной не менее 32 символов.")


def _token_ok(request: Request, secret: str) -> bool:
    given = (request.headers.get(TOKEN_HEADER)
             or request.cookies.get(TOKEN_COOKIE) or "")
    return hmac.compare_digest(given.encode(), secret.encode())


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    # Старый интерфейс использует inline обработчики; unsafe-inline пока нужен.
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "connect-src 'self'; media-src 'self' blob:; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def protect_response(request: Request, response: Response) -> Response:
    for k, v in SECURITY_HEADERS.items():
        # Встроенная справка FastAPI уже использует эти CDN. Исключение только
        # для справки; основной интерфейс и API сохраняют same-origin CSP.
        if (k == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc")
                and response.status_code == 200):
            asset = ("https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/"
                     if request.url.path == "/docs" else "https://cdn.jsdelivr.net/npm/redoc@2/bundles/")
            v = v.replace("script-src 'self' 'unsafe-inline'", f"script-src 'self' 'unsafe-inline' {asset}")
            v = v.replace("style-src 'self' 'unsafe-inline'",
                          f"style-src 'self' 'unsafe-inline' {asset} https://fonts.googleapis.com")
            v = v.replace("img-src 'self' data: blob:",
                          "img-src 'self' data: blob: https://fastapi.tiangolo.com/img/")
            v += "; font-src 'self' https://fonts.gstatic.com"
            if request.url.path == "/redoc":
                v = v.replace("https://fastapi.tiangolo.com/img/",
                              "https://fastapi.tiangolo.com/img/ https://cdn.redoc.ly/redoc/")
                v += "; worker-src 'self' blob:"
        response.headers.setdefault(k, v)
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=86400")
    if (request.url.path.startswith("/api/") or response.status_code >= 400
            or "set-cookie" in response.headers or "token" in request.query_params):
        response.headers["Cache-Control"] = "no-store"
    return response


async def _guard(request: Request, call_next) -> Response:  # noqa: ANN001
    headers = request.headers
    host = headers.get("host")
    remote = (not is_loopback(config.HOST)
              or bool(request.client and not is_loopback(request.client.host)))
    try:
        validate_network(remote)
    except ValueError:
        return PlainTextResponse("Сетевой доступ не настроен: нужны HTTPS и FARM_TOKEN.", status_code=503)
    if remote and request.url.scheme != "https":
        return PlainTextResponse("Доступ по сети возможен только через HTTPS.", status_code=403)
    if not host_allowed(host):
        return PlainTextResponse(
            "недопустимый Host. Откройте ферму по https://127.0.0.1:8777 или добавьте "
            "имя в FARM_ALLOWED_HOSTS", status_code=403)
    # Некоторые GET запускают захват/запись экрана. SOP скрывает ответ, но не
    # предотвращает действие, поэтому для API проверяем источник и у GET.
    api_request = request.url.path.startswith("/api/")
    if api_request and headers.get("sec-fetch-site") == "cross-site":
        return PlainTextResponse("запрос с чужой страницы отклонён", status_code=403)
    method = "POST" if api_request else request.method
    if not origin_allowed(method, host, headers.get("origin"), headers.get("referer"),
                          request.url.scheme):
        return PlainTextResponse("запрос с чужой страницы отклонён", status_code=403)

    secret = token()
    if secret:
        given = request.query_params.get("token")
        if request.method == "GET" and request.url.path == "/" and given is not None:
            if not hmac.compare_digest(given.encode(), secret.encode()):
                if not LOGIN_LIMITER.allow(peer_key(request.scope)):
                    return PlainTextResponse("Слишком много попыток входа.", status_code=429,
                                             headers={"Retry-After": "6"})
                return PlainTextResponse("неверный токен", status_code=401)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(TOKEN_COOKIE, secret, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/", max_age=60 * 60 * 12)
            return resp
        if not _token_ok(request, secret):
            if not LOGIN_LIMITER.allow(peer_key(request.scope)):
                return PlainTextResponse("Слишком много попыток входа.", status_code=429,
                                         headers={"Retry-After": "6"})
            return PlainTextResponse(
                "нужен токен фермы: откройте /?token=<FARM_TOKEN>", status_code=401)

    return await call_next(request)


async def guard(request: Request, call_next) -> Response:  # noqa: ANN001
    return protect_response(request, await _guard(request, call_next))
