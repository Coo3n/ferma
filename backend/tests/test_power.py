from farm import config
from farm.devices.power import PowerGuard


def test_low_then_critical_then_rest_without_reaction():
    g = PowerGuard()
    assert g.update("a", 19, 30, False, now=0)["state"] == "low"
    assert g.update("a", 14, 30, False, now=10)["state"] == "critical"
    assert g.view("a", now=10)["grace_left"] == config.BATTERY_GRACE
    r = g.update("a", 13, 30, False, now=10 + config.BATTERY_GRACE)
    assert r["state"] == "rest" and r["entered_rest"] and "никто" in r["rest_reason"]


def test_ack_stops_timer_but_not_hard_stop():
    g = PowerGuard()
    g.update("a", 14, 30, False, now=0)
    g.ack("a")
    assert g.update("a", 12, 30, False, now=10_000)["state"] == "critical"
    assert g.update("a", 5, 30, False, now=10_001)["entered_rest"]


def test_charging_cancels_countdown():
    g = PowerGuard()
    g.update("a", 14, 30, False, now=0)
    assert g.update("a", 14, 30, True, now=5)["state"] == "ok"
    assert g.view("a", now=5)["grace_left"] is None


def test_overheat_rest_and_hysteresis_recovery():
    g = PowerGuard()
    assert g.update("a", 80, 47, False, now=0)["entered_rest"]
    assert g.update("a", 80, 43, False, now=1)["state"] == "rest"   # ещё горячий
    assert g.update("a", 80, 39, False, now=2)["state"] == "ok"


def test_battery_recovery_needs_resume_level():
    g = PowerGuard()
    g.update("a", 4, 30, False, now=0)
    assert g.update("a", 25, 30, False, now=1)["state"] == "rest"
    assert g.update("a", 25, 30, True, now=2)["state"] == "ok"      # на зарядке хватает 20
    g.update("b", 4, 30, False, now=0)
    assert g.update("b", 30, 30, False, now=1)["state"] == "ok"
