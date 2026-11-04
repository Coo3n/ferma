"""HTTPS по умолчанию; явный HTTP разрешён только для локальной разработки."""
from __future__ import annotations

import os
import ssl
from pathlib import Path

from . import config, security
from .http_protocol import BoundedH11Protocol


def enabled() -> bool:
    value = os.getenv("FARM_HTTPS", "1")
    if value not in ("0", "1"):
        raise ValueError("FARM_HTTPS должен быть 0 или 1.")
    return value == "1"


def certificate_paths() -> tuple[Path, Path]:
    cert, key = os.getenv("FARM_TLS_CERT"), os.getenv("FARM_TLS_KEY")
    if cert is not None or key is not None:
        if not cert or not cert.strip() or not key or not key.strip():
            raise ValueError("Задайте вместе FARM_TLS_CERT и FARM_TLS_KEY.")
        paths = (Path(cert).expanduser(), Path(key).expanduser())
        return tuple(p if p.is_absolute() else config.PROJECT_DIR / p for p in paths)
    return config.DATA_DIR / "tls" / "cert.pem", config.DATA_DIR / "tls" / "key.pem"


def browser_url() -> str:
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(config.HOST, config.HOST)
    if ":" in host:
        host = f"[{host}]"
    return f"{'https' if enabled() else 'http'}://{host}:{config.PORT}"


def uvicorn_options() -> dict:
    use_tls = enabled()
    security.validate_network()
    options = {"host": config.HOST, "port": config.PORT, "log_level": "warning",
               "proxy_headers": False, "access_log": False, "server_header": False,
               "limit_concurrency": 512, "timeout_keep_alive": 5,
               "backlog": 128, "h11_max_incomplete_event_size": 16384,
               "http": BoundedH11Protocol, "ws": "none"}
    if not use_tls:
        return options
    cert, key = certificate_paths()
    if not cert.is_file() or not key.is_file():
        raise ValueError("Нет TLS-сертификата. Выполните: python backend/tools/setup_https.py")
    if os.name != "nt" and key.stat().st_mode & 0o077:
        raise ValueError(f"Закройте доступ к приватному ключу: chmod 600 '{key}'")
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)  # minimum TLS 1.2
        context.load_cert_chain(str(cert), str(key))
    except (OSError, ssl.SSLError) as exc:
        raise ValueError("Не удалось загрузить TLS-сертификат и ключ: проверьте PEM и их соответствие.") from exc
    options.update(ssl_certfile=str(cert), ssl_keyfile=str(key),
                   ssl_version=ssl.PROTOCOL_TLS_SERVER,
                   ssl_ciphers="ECDHE+AESGCM:ECDHE+CHACHA20")
    return options


if __name__ == "__main__":
    try:
        uvicorn_options()
        print(browser_url())
    except ValueError as exc:
        raise SystemExit(str(exc))
