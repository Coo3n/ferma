"""Red-team harness: гоняет один сценарий на ферме в двух профилях — «bot»
(как есть, детерминированно) и «human» (та же логика плюс небольшая
случайная вариативность задержек и координат) — и проверяет, ловит ли
RiskDetector разницу. Главная метрика — false negative rate: доля ботовских
прогонов, которые детектор принял за человека.

Заодно собирает сигналы уровня флота (общая подсеть, повтор build
fingerprint между устройствами) и принимает два сигнала, которые в принципе
нельзя получить через голый adb — аппаратную аттестацию (Play Integrity) и
аккаунт-граф: параметры `attestation_by_serial` / `account_signals_by_serial`
ниже, подключаете их, когда появится реальный бэкенд приложения.

Это стенд для проверки ВАШЕГО ЖЕ детектора (`farm.redteam.detector`), а не
инструмент обхода боевых антифрод-систем реальных платформ: там совсем
другой набор сигналов (аппаратная аттестация как полноценная криптографика,
серверные ML-модели, сетевая репутация в масштабе интернета), которые здесь
не эмулируются и не обходятся.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..context import DeviceContext
from ..devices.registry import registry
from . import trace as tracemod
from .detector import RiskDetector, RiskResult
from .signals import (
    ActionEvent,
    build_fleet_stats,
    cross_run_coord_jitter,
    cross_run_interval_jitter,
    fleet_ip,
    snapshot_env,
    snapshot_sensors,
)

PROBE_PATH = Path(__file__).resolve().parent.parent.parent / "scenarios" / "_redteam_probe.py"


class RecordingContext:
    """Оборачивает DeviceContext: пишет лог действий во время прогона.

    В профиле human перед каждым тапом/свайпом добавляет небольшую паузу и
    сдвигает координаты на несколько пикселей — имитация того, что палец
    никогда не попадает дважды в одну точку и не жмёт с одинаковой скоростью.

    Ввод через ctx.back()/ctx.home() тут намеренно не перехватывается (они
    внутри вызывают key() у исходного контекста в обход обёртки) — сценарий
    для harness использует ctx.key("back")/ctx.key("home") напрямую.
    """

    JITTER_PX = 4.0
    JITTER_DELAY = (0.15, 0.6)

    def __init__(self, inner: DeviceContext, humanize: bool):
        self._inner = inner
        self.humanize = humanize
        self.actions: list[ActionEvent] = []

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def _maybe_delay(self) -> None:
        if self.humanize:
            self._inner.sleep(random.uniform(*self.JITTER_DELAY))

    def _to_pixels_jittered(self, x: float, y: float) -> tuple[float, float]:
        if isinstance(x, float) and isinstance(y, float) and 0 <= x <= 1 and 0 <= y <= 1:
            w, h = self._inner.size
            px, py = x * w, y * h
        else:
            px, py = float(x), float(y)
        if self.humanize:
            px += random.uniform(-self.JITTER_PX, self.JITTER_PX)
            py += random.uniform(-self.JITTER_PX, self.JITTER_PX)
        return px, py

    def tap(self, x, y) -> None:
        self._maybe_delay()
        px, py = self._to_pixels_jittered(x, y)
        self.actions.append(ActionEvent(t=time.time(), kind="tap", x=px, y=py))
        self._inner.tap(px, py)

    def long_tap(self, x, y, duration: float = 0.8) -> None:
        self._maybe_delay()
        px, py = self._to_pixels_jittered(x, y)
        if self.humanize:
            duration = max(0.2, duration + random.uniform(-0.05, 0.15))
        self.actions.append(ActionEvent(t=time.time(), kind="long_tap", x=px, y=py))
        self._inner.long_tap(px, py, duration)

    def swipe(self, x1, y1, x2, y2, duration: float = 0.25) -> None:
        self._maybe_delay()
        px1, py1 = self._to_pixels_jittered(x1, y1)
        px2, py2 = self._to_pixels_jittered(x2, y2)
        if self.humanize:
            duration = max(0.1, duration + random.uniform(-0.05, 0.1))
        self.actions.append(ActionEvent(t=time.time(), kind="swipe", x=px1, y=py1))
        self._inner.swipe(px1, py1, px2, py2, duration)

    def scroll_down(self, times: int = 1) -> None:
        for _ in range(times):
            self.swipe(0.5, 0.75, 0.5, 0.3, 0.25)
            self._inner.sleep(random.uniform(0.2, 0.6) if self.humanize else 0.3)

    def scroll_up(self, times: int = 1) -> None:
        for _ in range(times):
            self.swipe(0.5, 0.3, 0.5, 0.75, 0.25)
            self._inner.sleep(random.uniform(0.2, 0.6) if self.humanize else 0.3)

    def key(self, name: str) -> None:
        self._maybe_delay()
        self.actions.append(ActionEvent(t=time.time(), kind="key"))
        self._inner.key(name)


@dataclass
class RunRecord:
    profile: str
    serial: str
    rep: int
    actions: list[ActionEvent] = field(default_factory=list)
    gesture: dict | None = None
    result: RiskResult | None = None


def _load_probe():
    spec = importlib.util.spec_from_file_location("farm_redteam_probe", PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_one(serial: str, profile: str, rep: int, artifacts_dir: Path) -> RunRecord:
    probe = _load_probe()
    inner = DeviceContext(serial=serial, artifacts_dir=artifacts_dir, device_name=serial)
    rec_ctx = RecordingContext(inner, humanize=(profile == "human"))
    probe.run(rec_ctx)
    gesture = tracemod.trace_gesture(serial, lambda: inner.tap(0.5, 0.5))
    return RunRecord(profile=profile, serial=serial, rep=rep, actions=rec_ctx.actions, gesture=gesture)


def run_harness(
    serials: list[str],
    repeats: int = 5,
    profiles: tuple[str, ...] = ("bot", "human"),
    detector: RiskDetector | None = None,
    attestation_by_serial: dict[str, str] | None = None,
    account_signals_by_serial: dict[str, dict] | None = None,
) -> dict:
    if not serials:
        raise ValueError("нужен хотя бы один serial")
    detector = detector or RiskDetector()
    attestation_by_serial = attestation_by_serial or {}
    account_signals_by_serial = account_signals_by_serial or {}

    run_id = uuid.uuid4().hex[:8]
    art_dir = Path(config.ARTIFACTS_DIR) / "redteam" / run_id
    art_dir.mkdir(parents=True, exist_ok=True)

    env_by_serial = {serial: snapshot_env(serial) for serial in serials}
    sensors_by_serial = {serial: snapshot_sensors(serial) for serial in serials}
    ips_by_serial = {serial: fleet_ip(serial) for serial in serials}
    fleet_stats = build_fleet_stats(ips_by_serial, env_by_serial)

    records: list[RunRecord] = []
    runs_by_key: dict[tuple[str, str], list[list[ActionEvent]]] = {}

    for serial in serials:
        for profile in profiles:
            for rep in range(repeats):
                rec = run_one(serial, profile, rep, art_dir)
                records.append(rec)
                runs_by_key.setdefault((serial, profile), []).append(rec.actions)

    for rec in records:
        history = runs_by_key[(rec.serial, rec.profile)]
        fleet = fleet_stats.get(rec.serial, {})
        features = {
            "cross_interval_std": cross_run_interval_jitter(history),
            "cross_coord_jitter": cross_run_coord_jitter(history),
            "env": env_by_serial[rec.serial],
            "sensors": sensors_by_serial[rec.serial],
            "gesture_trace": rec.gesture,
            "peers_same_subnet": fleet.get("peers_same_subnet"),
            "peers_same_fingerprint": fleet.get("peers_same_fingerprint"),
            "attestation": attestation_by_serial.get(rec.serial),
            "account_signal": account_signals_by_serial.get(rec.serial),
        }
        rec.result = detector.score(features)

    report = _build_report(run_id, records, fleet_stats)
    (art_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return report


def _build_report(run_id: str, records: list[RunRecord], fleet_stats: dict[str, dict]) -> dict:
    confusion: dict[tuple[str, str], int] = {}
    for rec in records:
        key = (rec.profile, rec.result.verdict)
        confusion[key] = confusion.get(key, 0) + 1

    def count(profile: str, verdict: str) -> int:
        return confusion.get((profile, verdict), 0)

    n_bot = sum(1 for r in records if r.profile == "bot")
    n_human = sum(1 for r in records if r.profile == "human")
    fn = count("bot", "human")
    fp = count("human", "bot")

    per_run = [
        {
            "serial": r.serial,
            "profile": r.profile,
            "rep": r.rep,
            "score": round(r.result.score, 1),
            "verdict": r.result.verdict,
            "top_signals": [
                {"name": s.name, "note": s.note, "contribution": round(s.contribution, 1)}
                for s in r.result.top_signals()
            ],
        }
        for r in records
    ]

    return {
        "run_id": run_id,
        "n_runs": len(records),
        "n_bot_runs": n_bot,
        "n_human_runs": n_human,
        "false_negative_rate": round(fn / n_bot, 3) if n_bot else None,
        "false_positive_rate": round(fp / n_human, 3) if n_human else None,
        "confusion": {f"{p}->{v}": c for (p, v), c in confusion.items()},
        "fleet": fleet_stats,
        "runs": per_run,
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Red-team harness: bot vs human-like против RiskDetector фермы"
    )
    parser.add_argument("--serial", action="append", dest="serials", default=[],
                        help="серийник устройства (можно указать несколько раз)")
    parser.add_argument("--all", action="store_true", help="взять все онлайн-устройства из реестра")
    parser.add_argument("--repeats", type=int, default=5, help="повторов на профиль на устройство")
    parser.add_argument("--threshold", type=float, default=55.0, help="порог RiskDetector (0..100)")
    args = parser.parse_args()

    registry.refresh_once()
    serials = list(args.serials)
    if args.all:
        serials = registry.online_serials()
    if not serials:
        parser.error("укажите --serial SERIAL (можно несколько раз) или --all")

    report = run_harness(serials, repeats=args.repeats, detector=RiskDetector(threshold=args.threshold))

    print(f"\nRun {report['run_id']}: {report['n_runs']} прогонов "
          f"({report['n_bot_runs']} bot / {report['n_human_runs']} human-like)")
    print(f"False negative rate (бот прошёл как человек):     {report['false_negative_rate']}")
    print(f"False positive rate (human-like помечен как бот):  {report['false_positive_rate']}")
    print("Confusion:", report["confusion"])
    if report["fleet"]:
        print("\nФлот (сеть/прошивка):")
        for serial, stats in report["fleet"].items():
            print(f"  {serial}: ip={stats['ip'] or '?'} "
                  f"peers_subnet={stats['peers_same_subnet']} peers_fingerprint={stats['peers_same_fingerprint']}")
    print(f"\nПолный отчёт: {Path(config.ARTIFACTS_DIR) / 'redteam' / report['run_id'] / 'report.json'}")


if __name__ == "__main__":
    _cli()
