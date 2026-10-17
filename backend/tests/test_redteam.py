"""Логика red-team стенда (farm/redteam): устройство не нужно, только синтетика.

Сравниваются два синтетических профиля прогонов — «бот» (одинаковые координаты
и интервалы от прогона к прогону) и «человек» (с разбросом) — и проверяется,
что сигналы и детектор действительно видят разницу между ними. Плюс отдельно
каждый из добавленных сигналов (сенсоры, флот по сети/прошивке, raw-трассировка
жеста, аттестация и аккаунт-граф как pluggable-заглушки) проверяется в изоляции.
"""
import random

from farm.redteam.detector import RiskDetector
from farm.redteam.signals import (
    ActionEvent,
    EnvSnapshot,
    SensorProfile,
    build_fleet_stats,
    cross_run_coord_jitter,
    cross_run_interval_jitter,
    run_intervals,
    subnet_key,
)


def _bot_run(base_t=0.0):
    """Три тапа строго по одним и тем же координатам с одним и тем же интервалом."""
    return [
        ActionEvent(t=base_t + 0.0, kind="tap", x=100.0, y=200.0),
        ActionEvent(t=base_t + 1.0, kind="tap", x=300.0, y=400.0),
        ActionEvent(t=base_t + 2.0, kind="tap", x=500.0, y=600.0),
    ]


def _human_run(base_t=0.0, coord_noise=6.0, time_noise=0.4):
    return [
        ActionEvent(t=base_t + 0.0, kind="tap", x=100.0 + random.uniform(-coord_noise, coord_noise),
                    y=200.0 + random.uniform(-coord_noise, coord_noise)),
        ActionEvent(t=base_t + 1.0 + random.uniform(-time_noise, time_noise),
                    kind="tap", x=300.0 + random.uniform(-coord_noise, coord_noise),
                    y=400.0 + random.uniform(-coord_noise, coord_noise)),
        ActionEvent(t=base_t + 2.0 + random.uniform(-time_noise * 2, time_noise * 2),
                    kind="tap", x=500.0 + random.uniform(-coord_noise, coord_noise),
                    y=600.0 + random.uniform(-coord_noise, coord_noise)),
    ]


def _clean_env(serial="dev1"):
    return EnvSnapshot(serial=serial, debuggable="0", secure="1", build_tags="release-keys",
                        adb_enabled="0", su_present=False, uptime_s=3600.0,
                        battery_plugged="", battery_level=61)


def _farmy_env(serial="dev1"):
    return EnvSnapshot(serial=serial, debuggable="1", secure="0", build_tags="test-keys",
                        adb_enabled="1", su_present=True, uptime_s=30 * 86400.0,
                        battery_plugged="AC", battery_level=100)


# ---------------------------------------------------------------- тайминги/координаты

def test_run_intervals_считает_среднее_и_разброс():
    events = [ActionEvent(t=0.0, kind="tap"), ActionEvent(t=1.0, kind="tap"), ActionEvent(t=3.0, kind="tap")]
    mean, std = run_intervals(events)
    assert mean == 1.5
    assert std > 0


def test_бот_даёт_почти_нулевой_джиттер_координат_и_интервалов():
    bot_runs = [_bot_run() for _ in range(5)]
    assert cross_run_coord_jitter(bot_runs) == 0.0
    assert cross_run_interval_jitter(bot_runs) == 0.0


def test_у_человека_джиттер_координат_и_интервалов_заметно_больше_нуля():
    human_runs = [_human_run() for _ in range(5)]
    assert cross_run_coord_jitter(human_runs) > 1.0
    assert cross_run_interval_jitter(human_runs) > 0.05


def test_одного_прогона_недостаточно_для_кросс_ранового_джиттера():
    assert cross_run_coord_jitter([_bot_run()]) is None
    assert cross_run_interval_jitter([_bot_run()]) is None


# ---------------------------------------------------------------- флот: подсеть/прошивка

def test_subnet_key_режет_по_24():
    assert subnet_key("192.168.1.50") == "192.168.1"
    assert subnet_key("не.ip.адрес.тут") is None
    assert subnet_key("10.0.0") is None


def test_build_fleet_stats_считает_соседей_по_подсети_и_прошивке():
    ips = {"a": "192.168.1.10", "b": "192.168.1.11", "c": "10.0.0.5"}
    envs = {
        "a": EnvSnapshot(serial="a", fingerprint="fp-clone"),
        "b": EnvSnapshot(serial="b", fingerprint="fp-clone"),
        "c": EnvSnapshot(serial="c", fingerprint="fp-unique"),
    }
    stats = build_fleet_stats(ips, envs)
    assert stats["a"]["peers_same_subnet"] == 1
    assert stats["b"]["peers_same_subnet"] == 1
    assert stats["c"]["peers_same_subnet"] == 0
    assert stats["a"]["peers_same_fingerprint"] == 1
    assert stats["c"]["peers_same_fingerprint"] == 0


# ---------------------------------------------------------------- детектор целиком

def test_детектор_различает_ботовский_и_человеческий_профиль():
    detector = RiskDetector(threshold=55.0)

    bot_runs = [_bot_run() for _ in range(5)]
    bot_features = {
        "cross_interval_std": cross_run_interval_jitter(bot_runs),
        "cross_coord_jitter": cross_run_coord_jitter(bot_runs),
        "env": _farmy_env(),
    }

    human_runs = [_human_run() for _ in range(5)]
    human_features = {
        "cross_interval_std": cross_run_interval_jitter(human_runs),
        "cross_coord_jitter": cross_run_coord_jitter(human_runs),
        "env": _clean_env(),
    }

    bot_result = detector.score(bot_features)
    human_result = detector.score(human_features)

    assert bot_result.score > human_result.score
    assert bot_result.verdict == "bot"
    assert human_result.verdict == "human"


def test_подозрительные_env_флаги_поднимают_скор_сами_по_себе():
    detector = RiskDetector()
    neutral = {"cross_interval_std": 0.2, "cross_coord_jitter": 5.0, "env": _clean_env()}
    farmy = {"cross_interval_std": 0.2, "cross_coord_jitter": 5.0, "env": _farmy_env()}
    assert detector.score(farmy).score > detector.score(neutral).score


def test_детектор_видит_соседей_по_подсети_и_прошивке():
    detector = RiskDetector()
    lonely = {"peers_same_subnet": 0, "peers_same_fingerprint": 0}
    crowded = {"peers_same_subnet": 5, "peers_same_fingerprint": 5}
    assert detector.score(crowded).score > detector.score(lonely).score


def test_детектор_видит_отсутствующие_сенсоры():
    detector = RiskDetector()
    full = {"sensors": SensorProfile(serial="a", has_accelerometer=True, has_gyroscope=True,
                                      has_magnetometer=True, raw_len=500)}
    stripped = {"sensors": SensorProfile(serial="b", has_accelerometer=True, has_gyroscope=False,
                                          has_magnetometer=False, raw_len=500)}
    assert detector.score(stripped).score > detector.score(full).score


def test_детектор_видит_отсутствие_raw_touch_событий():
    detector = RiskDetector()
    injected = {"gesture_trace": {"n_samples": 0}}
    real = {"gesture_trace": {"n_samples": 12}}
    assert detector.score(injected).score > detector.score(real).score


def test_детектор_читает_вердикт_аттестации_если_он_передан():
    detector = RiskDetector()
    good = {"attestation": "MEETS_DEVICE_INTEGRITY"}
    bad = {"attestation": "FAILED"}
    missing = {"attestation": None}
    assert detector.score(good).score < detector.score(missing).score < detector.score(bad).score


def test_детектор_читает_аккаунт_сигнал_если_он_передан():
    detector = RiskDetector()
    normal = {"account_signal": {"accounts_per_device": 1, "actions_per_minute": 5}}
    farmy = {"account_signal": {"accounts_per_device": 10, "actions_per_minute": 40}}
    assert detector.score(farmy).score > detector.score(normal).score
