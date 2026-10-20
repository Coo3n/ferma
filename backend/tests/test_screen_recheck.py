"""«Разбудить» во время идущей проверки экрана: принудительная перепроверка
не теряется, а повторяется после текущей (иначе плашка «Экран выключен»
висела поверх проснувшегося телефона)."""
import threading

from farm.streaming import frames


def test_forced_refresh_is_queued_while_busy(monkeypatch):
    states = iter([{"on": False, "locked": False}, {"on": True, "locked": False}])
    gate = threading.Event()
    calls = []

    def fake_state(serial):
        calls.append(1)
        if len(calls) == 1:
            gate.wait(2)          # первая (обычная) проверка ещё идёт
        return next(states)

    monkeypatch.setattr(frames.adb, "screen_state", fake_state)
    monkeypatch.setattr(frames.time, "sleep", lambda s: None)
    frames._screen.pop("S1", None)
    frames.screen_refresh("S1")                 # обычная, зависла на gate
    frames.screen_refresh("S1", force=True)     # «разбудить» — не должна потеряться
    gate.set()
    for _ in range(200):
        if "S1" not in frames._screen_busy:
            break
        threading.Event().wait(0.01)
    assert len(calls) == 2
    assert frames.screen_info("S1") == {"on": True, "locked": False}
