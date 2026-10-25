"""ctx.budget — потолок действий за сутки на прогоне."""
import pytest

from farm import accounts, budget
from farm.context import DeviceContext, Finished


@pytest.fixture(autouse=True)
def _tmp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "BUDGET_FILE", tmp_path / "budget.json")
    monkeypatch.setattr(budget, "_data", None)
    yield


def _ctx(lines=None):
    return DeviceContext("s1", device_name="Телефон 3",
                         logger=lines.append if lines is not None else (lambda m: None))


def _bind(monkeypatch, acc):
    monkeypatch.setattr(accounts, "for_device", lambda serial, platform=None: acc)


def test_counts_on_the_account_not_the_phone(monkeypatch):
    _bind(monkeypatch, {"id": "a7", "login": "petya"})
    _ctx().budget("подписки", 5)
    assert budget.used("account:a7", "подписки") == 1
    assert budget.used("phone:s1", "подписки") == 0


def test_finishes_the_run_when_the_limit_is_reached(monkeypatch):
    _bind(monkeypatch, {"id": "a7", "login": "petya"})
    lines = []
    ctx = _ctx(lines)
    ctx.budget("подписки", 2)
    ctx.budget("подписки", 2)
    with pytest.raises(Finished) as e:
        ctx.budget("подписки", 2)
    assert "потолок за сутки исчерпан" in str(e.value)
    assert "подписки: 1 из 2" in lines[0]
    assert "останавливаюсь" in lines[-1]


def test_without_an_account_counts_on_the_phone_and_says_so(monkeypatch):
    _bind(monkeypatch, None)
    lines = []
    _ctx(lines).budget("подписки", 5)
    assert budget.used("phone:s1", "подписки") == 1
    assert "аккаунт не привязан" in lines[0]
    assert "Телефон 3" in lines[0]


def test_two_phones_on_one_account_share_the_ceiling(monkeypatch):
    _bind(monkeypatch, {"id": "a7", "login": "petya"})
    DeviceContext("s1", logger=lambda m: None).budget("подписки", 2)
    DeviceContext("s2", logger=lambda m: None).budget("подписки", 2)
    with pytest.raises(Finished):
        DeviceContext("s3", logger=lambda m: None).budget("подписки", 2)


def test_ceiling_inside_a_called_block_stops_the_whole_run(monkeypatch):
    """ctx.run гасит Finished («блок кончился»), и потолок не должен в это
    попасть: иначе вызывающий сценарий продолжит делать то же действие."""
    from farm import scenarios
    from farm.context import BudgetReached

    _bind(monkeypatch, {"id": "a7", "login": "petya"})

    class ФейкМодуль:
        def __init__(self, fn):
            self.run = fn

    def блок(ctx):
        ctx.budget("подписки", 1)

    реестр = {"sub": scenarios.Scenario(key="sub", name="sub", description="", params={},
                                        path="sub.py", mtime=0, module=ФейкМодуль(блок))}
    monkeypatch.setattr(scenarios, "get", lambda k: реестр.get(k))

    ctx = _ctx()
    ctx.run("sub")                     # первая подписка проходит
    with pytest.raises(BudgetReached):
        ctx.run("sub")                 # вторая — наружу, а не «блок закончен»


def test_budget_reached_is_a_success_for_the_runner():
    from farm.context import BudgetReached, Finished
    assert issubclass(BudgetReached, Finished)
