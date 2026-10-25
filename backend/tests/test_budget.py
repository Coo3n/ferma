"""Потолок действий за сутки: счётчики на аккаунт."""
import json
from datetime import date, timedelta

import pytest

from farm import budget


@pytest.fixture(autouse=True)
def _tmp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "BUDGET_FILE", tmp_path / "budget.json")
    monkeypatch.setattr(budget, "_data", None)
    yield


def test_counts_up_to_the_limit_then_refuses():
    for n in range(1, 4):
        assert budget.take("account:a", "подписки", 3) == (True, n)
    assert budget.take("account:a", "подписки", 3) == (False, 3)
    # отказ не увеличивает счётчик: иначе отчёт врал бы о допущенном
    assert budget.used("account:a", "подписки") == 3


def test_counters_are_separate_per_key_and_name():
    budget.take("account:a", "подписки", 10)
    budget.take("account:b", "подписки", 10)
    budget.take("account:a", "лайки", 10)
    assert budget.used("account:a", "подписки") == 1
    assert budget.used("account:b", "подписки") == 1
    assert budget.used("account:a", "лайки") == 1
    assert budget.used("account:a", "ничего") == 0


def test_raising_the_limit_lets_the_run_continue():
    assert budget.take("account:a", "подписки", 1) == (True, 1)
    assert budget.take("account:a", "подписки", 1)[0] is False
    assert budget.take("account:a", "подписки", 5) == (True, 2)


def test_survives_restart():
    budget.take("account:a", "подписки", 10)
    budget._data = None                 # как после перезапуска фермы
    assert budget.used("account:a", "подписки") == 1


def test_broken_file_starts_from_zero_without_raising():
    budget.BUDGET_FILE.write_text("{не json", "utf-8")
    budget._data = None
    assert budget.used("account:a", "подписки") == 0
    assert budget.take("account:a", "подписки", 2) == (True, 1)


def test_old_days_are_pruned_but_kept_days_stay():
    старый = (date.today() - timedelta(days=budget.KEEP_DAYS + 1)).isoformat()
    свежий = (date.today() - timedelta(days=1)).isoformat()
    budget.BUDGET_FILE.write_text(json.dumps({
        "account:a": {старый: {"подписки": 7}, свежий: {"подписки": 3}}}), "utf-8")
    budget._data = None
    assert budget.used("account:a", "подписки", day=старый) == 0
    assert budget.used("account:a", "подписки", day=свежий) == 3


def test_state_and_reset():
    budget.take("account:a", "подписки", 10)
    budget.take("account:a", "лайки", 10)
    assert budget.state() == {"account:a": {"подписки": 1, "лайки": 1}}
    assert budget.state("account:a") == {"подписки": 1, "лайки": 1}
    budget.reset("account:a", "лайки")
    assert budget.state("account:a") == {"подписки": 1}
    budget.reset("account:a")
    assert budget.state() == {}
