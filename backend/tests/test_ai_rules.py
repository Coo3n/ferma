"""Правила ревью без нейросети: нажатие по координатам и шаг без ожидания."""
from farm.vlm import review


def _steps():
    return [
        {"kind": "launch_app", "args": {"package": "com.android.settings"}},
        {"kind": "tap", "args": {"x": 0.5, "y": 0.2}, "selector": None, "texts": []},
        {"kind": "sleep", "args": {"seconds": 1}},
        {"kind": "key", "args": {"name": "home"}},
    ]


def test_coordinate_tap_is_flagged_without_inventing_a_fix():
    f = [x for x in review.rule_findings(_steps()) if x["id"].startswith("r-coord")]
    assert len(f) == 1 and f[0]["steps"] == [1] and f[0]["fix"] is None


def test_missing_wait_gets_concrete_insert_fix():
    f = {x["id"]: x for x in review.rule_findings(_steps())}
    assert "r-wait-0" in f and f["r-wait-0"]["fix"]["op"] == "insert" and f["r-wait-0"]["fix"]["index"] == 1
    assert f["r-wait-0"]["fix"]["step"]["kind"] == "sleep"
    assert "r-wait-1" not in f  # после тапа уже стоит sleep


def test_rule_findings_survive_validation():
    steps = _steps()
    good, dropped = review.validate_findings(review.rule_findings(steps), steps)
    assert dropped == 0 and good


def test_review_merges_rules_with_model(monkeypatch):
    monkeypatch.setattr(review, "_review_model", lambda steps: ([], 0))
    found, dropped = review.review(_steps())
    assert dropped == 0 and any(f["id"].startswith("r-") for f in found)
