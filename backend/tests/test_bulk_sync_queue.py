"""Очередь ведомых телефонов: разброс считается от нажатия, не копится,
а порядок жестов на одном телефоне сохраняется."""
import time

from farm.api import bulk


def _fresh(monkeypatch):
    monkeypatch.setattr(bulk, "_queues", {})
    monkeypatch.setattr(bulk, "_last_due", {})
    puts = []

    class Q:
        def put(self, item):
            puts.append(item)

    monkeypatch.setattr(bulk.queue, "Queue", Q)
    monkeypatch.setattr(bulk.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: None})())
    return puts


def test_lag_does_not_accumulate(monkeypatch):
    puts = _fresh(monkeypatch)
    start = time.monotonic()
    for _ in range(10):
        bulk._enqueue("s1", 1.0, lambda s: None)
    last_due = puts[-1][0]
    # 10 жестов с разбросом 1 с: последний не позже ~1 с + 10 мин. зазоров,
    # а не 10 с, как было при задержке «после предыдущего».
    assert last_due - start < 1.0 + 10 * bulk.MIN_GAP + 0.2


def test_order_kept_on_one_phone(monkeypatch):
    puts = _fresh(monkeypatch)
    bulk._enqueue("s1", 3.0, lambda s: None)   # первый жест — с большим разбросом
    bulk._enqueue("s1", 0.1, lambda s: None)   # второй — с маленьким
    assert puts[1][0] >= puts[0][0] + bulk.MIN_GAP   # второй не обгоняет первый


def test_phones_independent(monkeypatch):
    puts = _fresh(monkeypatch)
    bulk._enqueue("a", 3.0, lambda s: None)
    t0 = time.monotonic()
    bulk._enqueue("b", 0.0, lambda s: None)
    assert puts[1][0] - t0 < 0.1   # чужая очередь не тормозит
