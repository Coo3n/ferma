"""Математика человечных жестов — без устройства, с фиксированным зерном."""
import random

from farm.control import humanize


def rng():
    return random.Random(7)


def test_точка_остаётся_в_центральной_зоне_элемента():
    r = rng()
    for _ in range(500):
        x, y = humanize.point_in(0.2, 0.4, 0.6, 0.5, r)
        assert 0.2 < x < 0.6
        assert 0.4 < y < 0.5
        # не дальше SPREAD от центра в долях полуширины/полувысоты
        assert abs(x - 0.4) <= 0.2 * humanize.SPREAD + 1e-9
        assert abs(y - 0.45) <= 0.05 * humanize.SPREAD + 1e-9


def test_точки_не_повторяются():
    r = rng()
    points = {humanize.point_in(0, 0, 1, 1, r) for _ in range(20)}
    assert len(points) > 15


def test_безье_доходит_до_конечной_точки():
    r = rng()
    path = humanize.bezier(0, 0, 100, 200, 10, r)
    assert len(path) == 10
    assert path[-1] == (100.0, 200.0)


def test_безье_изгибается_а_не_прямая():
    r = rng()
    path = humanize.bezier(0, 0, 0, 100, 10, r)
    # прямой вертикальный свайп обязан уехать по x хоть немного
    assert any(abs(px) > 0.5 for px, _ in path[:-1])


def test_пауза_в_заданных_границах():
    r = rng()
    for _ in range(200):
        value = humanize.pause_time(0.4, 1.5, r)
        assert 0.4 <= value <= 1.5
