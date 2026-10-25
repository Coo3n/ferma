"""Настройки нейросети-помощника: переменные окружения → data/vlm.json → config.

Окружение важнее файла: админ, выставивший FARM_VLM=0 в сервисе, должен быть
уверен, что никакая галочка в интерфейсе кадры не отправит. Файл правят из
интерфейса, поэтому читается заново на каждый вызов — перезапуск фермы не
нужен. Значения из окружения в интерфейсе помечаются как «заданы сервером».

Выключено по умолчанию: скриншоты аккаунтов никуда не уходят без явного
включения.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .. import config

log = logging.getLogger("farm.vlm")

_lock = threading.RLock()

# поле -> (переменная окружения, тип)
FIELDS = {
    "enabled": ("FARM_VLM", bool),
    "url": ("FARM_VLM_URL", str),
    "model": ("FARM_VLM_MODEL", str),
    "key": ("FARM_VLM_KEY", str),
    "timeout": ("FARM_VLM_TIMEOUT", float),
    "max_per_job": ("FARM_VLM_MAX_PER_JOB", int),
    "max_per_day": ("FARM_VLM_MAX_PER_DAY", int),
    "max_width": ("FARM_VLM_MAX_WIDTH", int),
    "min_confidence": ("FARM_VLM_MIN_CONFIDENCE", float),
}
DEFAULTS = {
    "enabled": False, "url": "", "model": "", "key": "",
    "timeout": config.VLM_TIMEOUT, "max_per_job": config.VLM_MAX_PER_JOB,
    "max_per_day": config.VLM_MAX_PER_DAY, "max_width": config.VLM_MAX_WIDTH,
    "min_confidence": 0.6,
}
MASK = "••••••••"


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    url: str = ""
    model: str = ""
    key: str = ""
    timeout: float = 30.0
    max_per_job: int = 3
    max_per_day: int = 200
    max_width: int = 720
    min_confidence: float = 0.6


def _file() -> dict:
    try:
        raw = json.loads(Path(config.VLM_FILE).read_text("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("файл настроек нейросети не читается (%s) — беру значения по умолчанию", e)
        return {}
    return raw if isinstance(raw, dict) else {}


def _coerce(value, kind):
    if kind is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind is str:
        return str(value or "").strip()
    return kind(value)


def _from_env() -> dict:
    out = {}
    for name, (var, kind) in FIELDS.items():
        raw = os.environ.get(var)
        if raw is None or raw.strip() == "":
            continue
        try:
            out[name] = _coerce(raw, kind)
        except (TypeError, ValueError):
            log.warning("%s=%r не разобрать — игнорирую", var, raw)
    return out


def locked() -> list:
    """Какие поля заданы окружением (в интерфейсе их менять бессмысленно)."""
    return sorted(_from_env())


def get() -> Settings:
    merged = dict(DEFAULTS)
    for name, value in _file().items():
        if name in FIELDS:
            try:
                merged[name] = _coerce(value, FIELDS[name][1])
            except (TypeError, ValueError):
                pass
    merged.update(_from_env())
    # Нижние границы: ноль/минус в лимитах означали бы «без лимита» по ошибке.
    merged["timeout"] = max(1.0, float(merged["timeout"]))
    merged["max_per_job"] = max(0, int(merged["max_per_job"]))
    merged["max_per_day"] = max(0, int(merged["max_per_day"]))
    merged["max_width"] = max(160, int(merged["max_width"]))
    merged["min_confidence"] = min(1.0, max(0.0, float(merged["min_confidence"])))
    return Settings(**merged)


def enabled() -> bool:
    s = get()
    return bool(s.enabled and s.url)


def save(patch: dict) -> None:
    """Дописать поля в data/vlm.json. Неизвестные ключи игнорируются."""
    with _lock:
        data = _file()
        for name, value in patch.items():
            if name in FIELDS:
                data[name] = value
        path = Path(config.VLM_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        try:
            tmp.chmod(0o600)   # в файле ключ доступа
        except OSError:
            pass
        tmp.replace(path)


def public() -> dict:
    """Настройки для интерфейса: ключ только маской."""
    s = get()
    d = {name: getattr(s, name) for name in FIELDS}
    d["key"] = MASK if s.key else ""
    d["locked"] = locked()
    return d
