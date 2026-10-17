"""Стабильность экрана: два одинаковых дампа подряд. Устройство не нужно —
dump и sleep подменяются аргументами."""
import itertools

from farm.control import stability


def test_стабильность_после_двух_одинаковых_дампов():
    dumps = iter(["<a/>", "<b/>", "<b/>"])
    assert stability.wait_stable(
        "x", timeout=5, quiet=0, dump=lambda: next(dumps), sleep=lambda s: None,
    ) is True


def test_вечная_анимация_даёт_таймаут():
    counter = itertools.count()
    assert stability.wait_stable(
        "x", timeout=0.05, quiet=0, dump=lambda: str(next(counter)),
        sleep=lambda s: None,
    ) is False


def test_упавший_дамп_не_роняет_шаг():
    def boom():
        raise RuntimeError("adb упал")

    assert stability.wait_stable(
        "x", timeout=1, quiet=0, dump=boom, sleep=lambda s: None,
    ) is False
