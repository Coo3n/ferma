"""Разбор прокси аккаунта для системного прокси телефона.

Чистый модуль: ни adb, ни диска. Системный прокси Android
(`settings put global http_proxy host:port`) не умеет логин и пароль, поэтому
прокси с авторизацией отвергается. Главное правило модуля: исходная строка
никогда не попадает ни в текст ошибки, ни в лог — в ней может лежать пароль.
"""
from __future__ import annotations

import re

HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z")

WITH_LOGIN = ("прокси с логином не поддерживается системным прокси телефона — "
              "нужен прокси без логина или привязка по IP")


class ProxyError(ValueError):
    """Причина по-русски; пароль в неё не попадает."""


def system_proxy(raw) -> str:
    """'host:port' для `settings put global http_proxy` или ProxyError."""
    text = str(raw or "").strip()
    if not text:
        raise ProxyError("у аккаунта не задан прокси — впишите его в разделе «Аккаунты»")
    if "://" in text:
        scheme, _, text = text.partition("://")
        if scheme.lower() != "http":
            raise ProxyError("системный прокси телефона работает только с http-прокси")
    if "@" in text:
        raise ProxyError(WITH_LOGIN)
    parts = text.split(":")
    if len(parts) > 2:
        # host:port:user:pass (и любые другие длинные формы) — с авторизацией
        raise ProxyError(WITH_LOGIN)
    if len(parts) != 2 or not HOST_RE.match(parts[0]) or not parts[1].isdigit() \
            or not 1 <= int(parts[1]) <= 65535:
        raise ProxyError("прокси аккаунта в непонятном виде — нужен host:port")
    return f"{parts[0]}:{int(parts[1])}"
