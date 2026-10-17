"""Итог прогонов сценария: сколько прошло, сколько упало."""
from farm.devices.runner import FAILED, PASSED, QUEUED, Job, Runner


def _job(scenario_key: str, status: str) -> Job:
    return Job(id=f"{scenario_key}-{status}-{id(object())}",
               scenario_key=scenario_key, scenario_name=scenario_key,
               serial="dev1", device_name="dev1", params={}, status=status)


def test_считает_только_свой_сценарий():
    runner = Runner()
    for j in [_job("a", PASSED), _job("a", FAILED), _job("b", PASSED)]:
        runner.jobs[j.id] = j
        runner.order.append(j.id)

    stats = runner.scenario_stats("a")
    assert stats == {"passed": 1, "failed": 1}


def test_незавершённые_не_считаются():
    runner = Runner()
    for j in [_job("a", PASSED), _job("a", QUEUED)]:
        runner.jobs[j.id] = j
        runner.order.append(j.id)

    assert runner.scenario_stats("a") == {"passed": 1, "failed": 0}


def test_пустая_история_даёт_нули():
    runner = Runner()
    assert runner.scenario_stats("нет-такого") == {"passed": 0, "failed": 0}


def test_limit_режет_старые_попытки():
    runner = Runner()
    # порядок в self.order — от старых к новым; scenario_stats идёт с конца
    for i in range(5):
        j = _job("a", PASSED if i < 3 else FAILED)
        runner.jobs[j.id] = j
        runner.order.append(j.id)

    stats = runner.scenario_stats("a", limit=2)
    assert stats["passed"] + stats["failed"] == 2
    assert stats == {"passed": 0, "failed": 2}   # два последних — FAILED
