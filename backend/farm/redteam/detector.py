"""Наивный risk-scoring детектор фермы.

Одиннадцать сигналов трёх родов:

- то, что реально меряется через adb здесь и сейчас (тайминги, координаты,
  raw-трассировка тача, сенсоры, adb/root-флаги, заряд, аптайм, общая
  подсеть по флоту, повтор build fingerprint по флоту);
- то, что принципиально нельзя получить без вашего бэкенда, но для чего
  оставлен параметр — сюда подставляется реальное значение, когда оно
  появится (аппаратная аттестация Play Integrity, аккаунт-граф);
- всё это — учебная стартовая точка: веса и пороги подбираются под ваши
  реальные данные через `detector.register(...)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

Check = Callable[[dict], "tuple[float, str]"]


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass
class SignalResult:
    name: str
    value: float  # 0..1 — насколько похоже на бота
    weight: float
    note: str = ""

    @property
    def contribution(self) -> float:
        return self.value * self.weight


@dataclass
class RiskResult:
    score: float  # 0..100
    verdict: str  # "human" | "bot"
    signals: list[SignalResult] = field(default_factory=list)

    def top_signals(self, n: int = 3) -> list[SignalResult]:
        return sorted(self.signals, key=lambda s: s.contribution, reverse=True)[:n]


class RiskDetector:
    def __init__(self, threshold: float = 55.0):
        self.threshold = threshold
        self._checks: list[tuple[str, float, Check]] = []
        self._register_defaults()

    def register(self, name: str, weight: float, fn: Check) -> None:
        self._checks.append((name, weight, fn))

    def _register_defaults(self) -> None:
        # аппаратная аттестация — самый сильный из всех фильтров, но её
        # нельзя получить через голый adb: значение должно прийти от вашего
        # бэкенда (вердикт Play Integrity), сюда — только точка подключения
        self.register("device_attestation", 30, self._check_attestation)

        # энтропия сенсоров: на платах без корпуса/экрана гироскоп или
        # магнитометр нередко физически не распаяны или отключены в прошивке
        self.register("sensor_profile", 15, self._check_sensors)

        # биометрия жеста: точность повторов + прошёл ли жест через ядро
        self.register("timing_regularity", 10, self._check_timing)
        self.register("coord_precision", 10, self._check_coords)
        self.register("gesture_trace", 15, self._check_gesture_trace)

        # сетевой и аккаунт-граф
        self.register("network_subnet", 12, self._check_network)
        self.register("fleet_fingerprint", 8, self._check_fingerprint)
        self.register("account_graph", 15, self._check_account)

        # окружение и жизненный цикл устройства
        self.register("env_flags", 10, self._check_env)
        self.register("power_pattern", 5, self._check_power)
        self.register("fleet_uptime", 5, self._check_uptime)

    # ---------------------------------------------------------------- проверки

    def _check_attestation(self, f: dict) -> tuple[float, str]:
        verdict = f.get("attestation")
        if verdict is None:
            return 0.5, ("вердикт Play Integrity не передан — из голого adb его не получить, "
                         "должен приходить из вашего приложения на бэкенд")
        ok = {"MEETS_DEVICE_INTEGRITY", "MEETS_STRONG_INTEGRITY", "MEETS_BASIC_INTEGRITY"}
        if verdict in ok:
            return 0.05, f"Play Integrity: {verdict}"
        return 0.9, f"Play Integrity: {verdict} — аттестация не пройдена"

    def _check_sensors(self, f: dict) -> tuple[float, str]:
        sp = f.get("sensors")
        if sp is None or sp.raw_len == 0:
            return 0.5, "нет данных о сенсорах"
        missing = [name for name, present in (
            ("акселерометр", sp.has_accelerometer),
            ("гироскоп", sp.has_gyroscope),
            ("магнитометр", sp.has_magnetometer),
        ) if not present]
        if not missing:
            return 0.1, "акселерометр/гироскоп/магнитометр на месте"
        return len(missing) / 3, (
            "нет сенсоров: " + ", ".join(missing) +
            " — типично для эмулятора или платы, собранной только под управление по USB"
        )

    def _check_timing(self, f: dict) -> tuple[float, str]:
        std = f.get("cross_interval_std")
        if std is None:
            return 0.5, "нет повторов для сравнения"
        return _clip01(1 - std / 0.35), f"разброс интервалов между прогонами: {std * 1000:.0f} мс"

    def _check_coords(self, f: dict) -> tuple[float, str]:
        jitter = f.get("cross_coord_jitter")
        if jitter is None:
            return 0.5, "нет повторов для сравнения"
        return _clip01(1 - jitter / 6.0), f"разброс координат между прогонами: {jitter:.1f}px"

    def _check_gesture_trace(self, f: dict) -> tuple[float, str]:
        trace = f.get("gesture_trace")
        if trace is None:
            return 0.5, "raw-трассировку получить не удалось (нет доступа к узлу тачскрина)"
        if trace.get("n_samples", 0) == 0:
            return 0.9, "во время жеста ядро не увидело ни одного raw touch-события — похоже на программный инжект"
        return 0.1, f"{trace['n_samples']} raw-событий с тачскрина во время жеста"

    def _check_network(self, f: dict) -> tuple[float, str]:
        peers = f.get("peers_same_subnet")
        if peers is None:
            return 0.5, "нет сетевых данных"
        if peers == 0:
            return 0.1, "единственное устройство в своей подсети /24"
        return _clip01(peers / 5), f"{peers} других устройств фермы в той же подсети /24"

    def _check_fingerprint(self, f: dict) -> tuple[float, str]:
        peers = f.get("peers_same_fingerprint")
        if peers is None:
            return 0.5, "нет данных"
        if peers == 0:
            return 0.1, "уникальная build fingerprint в этом прогоне"
        return _clip01(peers / 5), f"{peers} других устройств с точно такой же build fingerprint"

    def _check_account(self, f: dict) -> tuple[float, str]:
        signal = f.get("account_signal")
        if signal is None:
            return 0.5, "сигнал аккаунт-графа не передан — его неоткуда взять без бэкенда приложения"
        accounts = signal.get("accounts_per_device", 0) or 0
        apm = signal.get("actions_per_minute", 0) or 0
        flags, notes = 0, []
        if accounts > 3:
            flags += 1; notes.append(f"{accounts} аккаунтов с одного устройства")
        if apm > 20:
            flags += 1; notes.append(f"{apm:.0f} действий/мин")
        return flags / 2, (", ".join(notes) or "паттерн аккаунта обычный")

    def _check_env(self, f: dict) -> tuple[float, str]:
        env = f.get("env")
        if env is None:
            return 0.5, "нет снимка окружения"
        flags, notes = 0, []
        if env.debuggable == "1":
            flags += 1; notes.append("ro.debuggable=1")
        if env.secure == "0":
            flags += 1; notes.append("ro.secure=0")
        if env.build_tags and "test-keys" in env.build_tags:
            flags += 1; notes.append("build tags: test-keys")
        if env.su_present:
            flags += 1; notes.append("su в PATH")
        if env.adb_enabled == "1":
            flags += 1; notes.append("adb включён в settings")
        return flags / 5, (", ".join(notes) or "чисто")

    def _check_power(self, f: dict) -> tuple[float, str]:
        env = f.get("env")
        if env is None:
            return 0.5, "нет снимка окружения"
        if env.battery_plugged and env.battery_level is not None and env.battery_level >= 95:
            return 0.8, f"на зарядке при {env.battery_level}% — типично для стойки, не для юзера в руке"
        return 0.1, "паттерн заряда обычный"

    def _check_uptime(self, f: dict) -> tuple[float, str]:
        env = f.get("env")
        if env is None or env.uptime_s is None:
            return 0.5, "нет данных об аптайме"
        days = env.uptime_s / 86400
        if days > 14:
            return 0.6, f"аптайм {days:.1f} дн. — устройство никто не перезагружает и не носит в кармане"
        return 0.15, f"аптайм {days:.1f} дн."

    def score(self, features: dict) -> RiskResult:
        signals = []
        for name, weight, fn in self._checks:
            value, note = fn(features)
            signals.append(SignalResult(name=name, value=_clip01(value), weight=weight, note=note))
        total_weight = sum(w for _, w, _ in self._checks) or 1.0
        raw = sum(s.contribution for s in signals)
        score = 100.0 * raw / total_weight
        verdict = "bot" if score >= self.threshold else "human"
        return RiskResult(score=score, verdict=verdict, signals=signals)
