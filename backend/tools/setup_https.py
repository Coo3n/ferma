"""Создать локальный TLS-сертификат: python backend/tools/setup_https.py.

Доверие ОС добавляется отдельно командой mkcert -install (может требовать пароль).
--host 192.168.1.5 добавляет адрес для LAN; --renew перевыпускает сертификат.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from farm import tls  # noqa: E402


def certificate_host(value: str) -> str:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
            raise argparse.ArgumentTypeError("Нужен IP-адрес или DNS-имя (без схемы и порта).")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", action="append", default=[], type=certificate_host)
    parser.add_argument("--renew", action="store_true")
    args = parser.parse_args()
    if not tls.enabled():
        tls.uvicorn_options()  # HTTP на сетевом адресе тоже должен завершиться ошибкой
        return
    cert, key = tls.certificate_paths()
    custom = "FARM_TLS_CERT" in os.environ or "FARM_TLS_KEY" in os.environ
    if custom or (cert.exists() and key.exists() and not args.renew):
        tls.uvicorn_options()
        return
    if (cert.exists() or key.exists()) and not args.renew:
        raise ValueError("Неполная пара сертификат/ключ. Для перевыпуска используйте --renew.")
    mkcert = shutil.which("mkcert")
    if not mkcert:
        raise ValueError("Нужен mkcert: macOS — brew install mkcert; Windows — choco install mkcert. "
                         "Инструкция: https://github.com/FiloSottile/mkcert")
    cert.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        cert.parent.chmod(0o700)
    # Генерируем во временной приватной папке, не трогая старую пару при ошибке mkcert.
    with tempfile.TemporaryDirectory(dir=cert.parent) as tmp:
        new_cert, new_key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
        subprocess.run([mkcert, "-cert-file", str(new_cert), "-key-file", str(new_key),
                        "localhost", "127.0.0.1", "::1", *args.host], check=True)
        new_key.chmod(0o600)
        os.replace(new_key, key)
        os.replace(new_cert, cert)
    print(f"Сертификат создан: {cert}")
    print("Для доверия браузера один раз выполните: mkcert -install")
    tls.uvicorn_options()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
