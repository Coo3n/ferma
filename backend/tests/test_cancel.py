"""Отмена задачи: видна сразу, срабатывает быстро.

Прервать чужой поток посреди шага нельзя, поэтому отмена кооперативная.
Раньше это значило, что после нажатия задача секунд десять оставалась в
статусе «работает» — и человек жал ещё раз, считая кнопку сломанной. Здесь
проверяется обе половины исправления: мгновенный статус CANCELLING и
нарезанное ожидание элемента, которое спрашивает отмену раз в секунду.
"""
from __future__ import annotations

import threading
import time

import pytest

from farm import config
from farm import deviations as dv
from farm.context import Cancelled, DeviceContext
from farm.devices import runner as R


@pytest.fixture
def задача():
    dv.deviations.clear()
    job = R.Job(id="c1", scenario_key="login", scenario_name="Вход",
                serial="emulator-5554", device_name="Pixel-1", params={})
    job.status = R.RUNNING
    R.runner.jobs[job.id] = job
    R.runner.order.append(job.id)
    yield job
    R.runner.jobs.pop(job.id, None)
    try:
        R.runner.order.remove(job.id)
    except ValueError:
        pass
    dv.deviations.clear()


def test_отмена_работающей_видна_сразу(задача):
    """Статус меняется в момент нажатия, а не когда шаг дойдёт до проверки."""
    assert R.runner.cancel("c1") is True
    assert задача.status == R.CANCELLING
    assert задача.status in R.ACTIVE      # устройство ещё занято
    assert "отмена принята" in " ".join(задача.lines)


def test_повторная_отмена_ничего_не_обещает(задача):
    R.runner.cancel("c1")
    assert R.runner.cancel("c1") is False
    assert R.runner.cancel_all() == 0


def test_отмена_из_очереди_завершает_сразу(задача):
    задача.status = R.QUEUED
    assert R.runner.cancel("c1") is True
    assert задача.status == R.CANCELLED
    assert задача.finished_at is not None


def test_отмена_стоящей_не_возвращает_её_в_работу(задача, monkeypatch):
    """`_hold` после побудки ставил RUNNING и затирал принятую отмену."""
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 5)

    def отменить():
        for _ in range(500):
            if задача.status == R.HELD:
                break
            time.sleep(0.01)
        R.runner.cancel("c1")

    поток = threading.Thread(target=отменить)
    поток.start()
    R._hold(задача, "не найден элемент")
    поток.join()
    assert задача.status == R.CANCELLING


def test_отменяемая_задача_считается_в_статистике(задача):
    R.runner.cancel("c1")
    assert R.runner.stats()[R.CANCELLING] == 1


def test_отменяемую_задачу_нельзя_удалить_из_журнала(задача):
    R.runner.cancel("c1")
    assert R.runner.delete("c1") is False
    assert R.runner.clear_finished() == 0


# ------------------------------------------------------------------ ожидание

class ЭлементКоторогоНет:
    """Заглушка u2: считает, сколько раз её ждали и какими кусками."""

    def __init__(self) -> None:
        self.куски: list[float] = []

    def wait(self, timeout: float = 0) -> bool:
        self.куски.append(timeout)
        time.sleep(min(timeout, 0.05))
        return False


def _контекст(el, отменено):
    ctx = DeviceContext("s", logger=lambda m: None,
                        cancel_check=lambda: отменено())
    ctx.require_u2 = lambda: (lambda **sel: el)
    return ctx


def test_ожидание_элемента_нарезано_на_куски():
    """Одним `wait(10)` отмену внутри ожидания не спросить."""
    el = ЭлементКоторогоНет()
    ctx = _контекст(el, lambda: False)
    assert ctx.find(timeout=3, text="Войти") is None
    assert len(el.куски) > 1
    assert max(el.куски) <= 1.0


def test_отмена_прерывает_ожидание_элемента():
    el = ЭлементКоторогоНет()
    отменено = [False]

    def проверка():
        # первая проверка проходит, вторая — уже отменено: так выглядит
        # нажатие «отменить» посреди ожидания
        было = отменено[0]
        отменено[0] = True
        return было

    ctx = _контекст(el, проверка)
    with pytest.raises(Cancelled):
        ctx.find(timeout=30, text="Войти")
    assert len(el.куски) == 1      # не досидели до конца таймаута
