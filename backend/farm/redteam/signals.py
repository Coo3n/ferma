"""Сигналы для red-team детектора фермы.

Отвечает на вопрос «чем реально можно отличить ферму от живого пользователя
через обычный adb, без root и без серверной телеметрии приложения» — плюс
интерфейс для пары сигналов, которые физически нельзя получить через adb
(аппаратная аттестация, аккаунт-граф) и которые должны приходить из вашего
бэкенда — см. параметры `attestation_by_serial` / `account_signals_by_serial`
в `harness.run_harness`.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .. import adb


@dataclass
class ActionEvent:
    """Одно записанное действие ввода за время прогона сценария."""
    t: float
    kind: str  # "tap" | "long_tap" | "swipe" | "key"
    x: float | None = None
    y: float | None = None


@dataclass
class EnvSnapshot:
    """Разовый снимок окружения устройства — всё, что реально спросить через adb без root."""
    serial: str
    debuggable: str = ""
    secure: str = ""
    build_tags: str = ""
    adb_enabled: str = ""
    su_present: bool = False
    uptime_s: float | None = None
    battery_plugged: str = ""
    battery_level: int | None = None
    fingerprint: str = ""


def snapshot_env(serial: str) -> EnvSnapshot:
    snap = EnvSnapshot(serial=serial)
    snap.debuggable = adb.getprop(serial, "ro.debuggable")
    snap.secure = adb.getprop(serial, "ro.secure")
    snap.build_tags = adb.getprop(serial, "ro.build.tags")
    snap.fingerprint = adb.getprop(serial, "ro.build.fingerprint")
    try:
        snap.adb_enabled = adb.shell(serial, ["settings", "get", "global", "adb_enabled"], timeout=10).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        snap.su_present = bool(adb.shell(serial, ["which", "su"], timeout=10).strip())
    except Exception:  # noqa: BLE001
        pass
    try:
        raw_uptime = adb.shell(serial, ["cat", "/proc/uptime"], timeout=10).strip()
        snap.uptime_s = float(raw_uptime.split()[0])
    except Exception:  # noqa: BLE001
        pass
    b = adb.battery(serial)
    snap.battery_plugged = b.get("plugged", "")
    snap.battery_level = b.get("level")
    return snap


@dataclass
class SensorProfile:
    """Присутствие базовых сенсоров движения по `dumpsys sensorservice`.

    Эвристика по подстрокам в дампе: формат немного отличается между
    OEM/версиями Android, но названия базовых сенсоров движения в нём есть
    почти всегда. Проверьте на своих реальных устройствах и поправьте при
    необходимости — `raw_len` показывает, был ли вообще получен непустой дамп.
    """
    serial: str
    has_accelerometer: bool = False
    has_gyroscope: bool = False
    has_magnetometer: bool = False
    raw_len: int = 0


def snapshot_sensors(serial: str) -> SensorProfile:
    try:
        out = adb.shell(serial, ["dumpsys", "sensorservice"], timeout=10)
    except Exception:  # noqa: BLE001
        out = ""
    low = out.lower()
    return SensorProfile(
        serial=serial,
        has_accelerometer="accelerometer" in low,
        has_gyroscope="gyroscope" in low,
        has_magnetometer=("magnetic field" in low or "magnetometer" in low),
        raw_len=len(out),
    )


# ---------------------------------------------------------------- сеть/флот

def fleet_ip(serial: str) -> str:
    """IP устройства для сравнения по подсети.

    Для сетевой платы (`host:port`) — сам host из серийника, он и так известен
    без обращения к устройству. Для USB — Wi-Fi адрес телефона, если он у
    него вообще есть (см. `adb.device_ip`).
    """
    if adb.is_network_serial(serial):
        return serial.rsplit(":", 1)[0]
    return adb.device_ip(serial)


def subnet_key(ip: str) -> str | None:
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    return ".".join(parts[:3])


def build_fleet_stats(ips: dict[str, str], env_by_serial: dict[str, EnvSnapshot]) -> dict[str, dict]:
    """Для каждого устройства — сколько других устройств фермы делят с ним
    подсеть /24 и сколько делят точно такую же build fingerprint.
    """
    subnet_counts: dict[str, int] = {}
    subnet_of: dict[str, str | None] = {}
    for serial, ip in ips.items():
        key = subnet_key(ip)
        subnet_of[serial] = key
        if key:
            subnet_counts[key] = subnet_counts.get(key, 0) + 1

    fp_counts: dict[str, int] = {}
    for env in env_by_serial.values():
        if env.fingerprint:
            fp_counts[env.fingerprint] = fp_counts.get(env.fingerprint, 0) + 1

    stats: dict[str, dict] = {}
    for serial, ip in ips.items():
        key = subnet_of.get(serial)
        peers_subnet = (subnet_counts.get(key, 1) - 1) if key else 0
        env = env_by_serial.get(serial)
        peers_fp = (fp_counts.get(env.fingerprint, 1) - 1) if env and env.fingerprint else 0
        stats[serial] = {"ip": ip, "peers_same_subnet": peers_subnet, "peers_same_fingerprint": peers_fp}
    return stats


# ---------------------------------------------------------------- тайминги/геометрия

def _intervals(events: list[ActionEvent]) -> list[float]:
    ts = [e.t for e in events]
    return [b - a for a, b in zip(ts, ts[1:])]


def run_intervals(events: list[ActionEvent]) -> tuple[float, float]:
    """Средний интервал и разброс (std) между действиями внутри ОДНОГО прогона."""
    iv = _intervals(events)
    if not iv:
        return 0.0, 0.0
    mean = statistics.fmean(iv)
    std = statistics.pstdev(iv) if len(iv) > 1 else 0.0
    return mean, std


def cross_run_interval_jitter(runs: list[list[ActionEvent]]) -> float | None:
    """Насколько стабильны интервалы между действиями ОТ ПРОГОНА К ПРОГОНУ."""
    per_run = [_intervals(r) for r in runs if _intervals(r)]
    if len(per_run) < 2:
        return None
    length = min(len(iv) for iv in per_run)
    if not length:
        return None
    spreads = [statistics.pstdev([iv[i] for iv in per_run]) for i in range(length)]
    return statistics.fmean(spreads)


def cross_run_coord_jitter(runs: list[list[ActionEvent]]) -> float | None:
    """Насколько «прыгают» пиксельные координаты одного и того же по порядку
    действия между повторами. Бот тапает пиксель-в-пиксель; человек — никогда.
    """
    by_index: dict[int, list[tuple[float, float]]] = {}
    for run in runs:
        for i, e in enumerate(run):
            if e.x is None or e.y is None:
                continue
            by_index.setdefault(i, []).append((e.x, e.y))
    spreads = []
    for pts in by_index.values():
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        spreads.append(statistics.pstdev(xs) + statistics.pstdev(ys))
    return statistics.fmean(spreads) if spreads else None
