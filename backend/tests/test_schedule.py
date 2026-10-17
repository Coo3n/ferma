"""Смены: детерминированный план дня и логика «пора / пропустить»."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pytest

from farm import schedule as S

MON = date(2026, 10, 12)  # понедельник


def sched(**kw):
    base = {"name": "Утро", "scenario": "demo", "days": list(range(7)),
            "window": {"from": "10:00", "to": "14:00"}, "runs_per_day": 3}
    base.update(kw)
    out = S.normalize(base)
    out["id"] = kw.get("id", "abc")
    return out


# ------------------------------------------------------------------ план

def test_plan_deterministic():
    s = sched()
    assert S.plan_times(s, MON, "p1") == S.plan_times(s, MON, "p1")
    assert S.plan_times(s, MON, "p1") != S.plan_times(s, MON, "p2")
    assert S.plan_times(s, MON, "p1") != S.plan_times(s, MON + timedelta(days=7), "p1")


@pytest.mark.parametrize("runs", [1, 3, 10])
def test_plan_inside_window_and_spaced(runs):
    s = sched(runs_per_day=runs)
    lo, hi = datetime(2026, 10, 12, 10), datetime(2026, 10, 12, 14)
    for i in range(50):
        times = S.plan_times(s, MON, f"phone{i}")
        assert len(times) == runs
        assert all(lo <= t < hi for t in times)
        assert all((b - a).total_seconds() >= S.MIN_GAP_S for a, b in zip(times, times[1:]))


def test_narrow_window_cuts_runs_not_gap():
    s = sched(window={"from": "10:00", "to": "10:50"}, runs_per_day=10)
    times = S.plan_times(s, MON, "p")
    assert len(times) == 3
    assert all((b - a).total_seconds() >= S.MIN_GAP_S for a, b in zip(times, times[1:]))


def test_days_filter():
    s = sched(days=[0, 2])  # пн, ср
    assert S.plan_times(s, MON, "p")
    assert S.plan_times(s, MON + timedelta(days=1), "p") == []
    assert S.plan_times(s, MON + timedelta(days=2), "p")


def test_normalize_rejects_bad():
    with pytest.raises(ValueError):
        sched(window={"from": "14:00", "to": "10:00"})
    with pytest.raises(ValueError):
        sched(runs_per_day=11)
    with pytest.raises(ValueError):
        sched(target={"kind": "group", "value": ""})
    with pytest.raises(ValueError):
        sched(days=[])


# -------------------------------------------------------------- подмены

@dataclass
class Dev:
    serial: str
    online: bool = True
    busy_job: str | None = None
    group: str = ""
    enabled: bool = True
    tags: list = field(default_factory=list)

    @property
    def name(self):
        return self.serial


class FakeRegistry:
    def __init__(self, devs):
        self.devs = {d.serial: d for d in devs}

    def all(self):
        return list(self.devs.values())

    def get(self, serial):
        return self.devs.get(serial)


@dataclass
class Job:
    id: str


class FakeRunner:
    def __init__(self):
        self.calls = []

    def submit(self, key, serials, params=None, batch=None, **kw):
        self.calls.append((key, list(serials), batch))
        return [Job(f"j{len(self.calls)}")]


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def make(tmp_path, devs, runs=1, created=datetime(2026, 10, 12, 0, 0), **kw):
    clock = Clock(created)
    reg, run = FakeRegistry(devs), FakeRunner()
    sc = S.Scheduler(tmp_path / "s.json", runner=run, registry=reg, clock=clock)
    s = sc.create({"name": "Утро", "scenario": "demo", "runs_per_day": runs,
                   "window": {"from": "10:00", "to": "14:00"}, **kw})
    # Постоянный id — постоянный план: тесты не зависят от случайного uuid.
    sc._since["t1"] = sc._since.pop(s["id"])
    sc._items[0]["id"] = s["id"] = "t1"
    return sc, s, clock, reg, run


def test_target_kinds():
    devs = [Dev("a", group="G", tags=["x"]), Dev("b"), Dev("c", tags=["x"])]
    assert S.target_serials(sched(), devs) == ["a", "b", "c"]
    assert S.target_serials(sched(target={"kind": "group", "value": "G"}), devs) == ["a"]
    assert S.target_serials(sched(target={"kind": "tag", "value": "x"}), devs) == ["a", "c"]
    assert S.target_serials(sched(target={"kind": "serials", "value": ["z"]}), devs) == ["z"]


def test_due_starts_once_per_slot(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1")])
    at = S.plan_times(s, MON, "p1")[0]
    clock.now = at - timedelta(seconds=10)
    assert sc.tick() == 0
    clock.now = at + timedelta(seconds=5)
    assert sc.tick() == 1
    assert run.calls == [("demo", ["p1"], f"sch-{s['id']}-2026-10-12")]
    clock.now += timedelta(seconds=30)
    assert sc.tick() == 0
    slot = sc.plan(s["id"], MON)["phones"][0]["slots"][0]
    assert slot["status"] == S.STARTED and slot["job"] == "j1"


def test_state_survives_restart(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1")])
    at = S.plan_times(s, MON, "p1")[0]
    clock.now = at + timedelta(seconds=5)
    sc.tick()
    run2 = FakeRunner()
    sc2 = S.Scheduler(tmp_path / "s.json", runner=run2, registry=reg, clock=clock)
    clock.now += timedelta(seconds=30)
    assert sc2.tick() == 0 and run2.calls == []


def test_busy_retried_then_started(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1", busy_job="x")])
    at = S.plan_times(s, MON, "p1")[0]
    assert at + timedelta(seconds=S.RETRY_S * 2) < datetime(2026, 10, 12, 14)
    clock.now = at + timedelta(seconds=5)
    assert sc.tick() == 0
    slot = sc.plan(s["id"], MON)["phones"][0]["slots"][0]
    assert slot["status"] == S.WAIT and "занят" in slot["note"]
    reg.devs["p1"].busy_job = None
    clock.now += timedelta(seconds=60)          # повтор ещё не наступил
    assert sc.tick() == 0
    clock.now = at + timedelta(seconds=5 + S.RETRY_S)
    assert sc.tick() == 1


def test_offline_skipped_after_window(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1", online=False)])
    at = S.plan_times(s, MON, "p1")[0]
    clock.now = at + timedelta(seconds=5)
    sc.tick()
    clock.now = datetime(2026, 10, 12, 14, 0, 1)
    assert sc.tick() == 0
    slot = sc.plan(s["id"], MON)["phones"][0]["slots"][0]
    assert slot["status"] == S.SKIPPED and "не подключён" in slot["note"]
    assert run.calls == []


def test_slots_before_creation_skipped(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1")], created=datetime(2026, 10, 12, 13, 59))
    clock.now = datetime(2026, 10, 12, 13, 59, 30)
    assert sc.tick() == 0
    assert run.calls == []
    assert sc.plan(s["id"], MON)["phones"][0]["slots"][0]["status"] == S.SKIPPED


def test_late_catchup_spread(tmp_path):
    """Ферма проспала момент — запуск откладывается на случайные 0..5 мин."""
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1")])
    at = S.plan_times(s, MON, "p1")[0]
    clock.now = at + timedelta(seconds=S.LATE_S + 10)
    assert sc.tick() == 0
    clock.now += timedelta(seconds=S.CATCHUP_SPREAD_S + 1)
    assert sc.tick() == 1


def test_disabled_and_day_off(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1")], days=[1])  # только вторник
    clock.now = datetime(2026, 10, 12, 13, 59)
    assert sc.tick() == 0
    sc.toggle(s["id"], False)
    clock.now = datetime(2026, 10, 13, 13, 59)
    assert sc.tick() == 0 and run.calls == []


def test_next_run(tmp_path):
    sc, s, clock, reg, run = make(tmp_path, [Dev("p1"), Dev("p2")])
    first = min(S.plan_times(s, MON, p)[0] for p in ("p1", "p2"))
    assert sc.next_run(sc.get(s["id"])) == first.timestamp()
    clock.now = datetime(2026, 10, 12, 15)
    tomorrow = min(S.plan_times(s, MON + timedelta(days=1), p)[0] for p in ("p1", "p2"))
    assert sc.next_run(sc.get(s["id"])) == tomorrow.timestamp()
