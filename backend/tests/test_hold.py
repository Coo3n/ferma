"""Остановка на человеке: шаг промахнулся, задача ждёт решения.

Устройство не нужно: шаги подменены, а «человек» — обычная функция, которую
подставляет очередь. Проверяем ровно то, за что механизм отвечает: решение
применяется к живому прогону, потолки держат, а без очереди и без флага
поведение остаётся прежним.
"""
import threading
import time

import pytest

from farm import config, deviations as dv
from farm.context import (DeviceContext, HOLD_DROP, HOLD_RETRY, HOLD_SKIP,
                          Cancelled, StepFailed)
from farm.devices import runner as R


class КликCtx(DeviceContext):
    """ctx, у которого элемент находится только с N-й попытки."""

    def __init__(self, найти_с_попытки=99, **kw):
        super().__init__("s", logger=lambda m: None, **kw)
        self.найти_с_попытки = найти_с_попытки
        self.попытки = 0
        self.клики = 0

    def _settle(self):
        pass

    def _rescue(self):
        return False

    def find(self, timeout=10, **selector):
        self.попытки += 1
        return object() if self.попытки >= self.найти_с_попытки else None

    def _scroll_to(self, **selector):
        return None

    def _click_el(self, el):
        self.клики += 1


# ------------------------------------------------------------------ решения

def test_без_очереди_шаг_падает_как_раньше():
    """Сценарий, запущенный не из очереди, спрашивать некого — и не должен."""
    ctx = КликCtx()
    with pytest.raises(StepFailed, match="не найден элемент"):
        ctx.click(timeout=0, text="Войти")


def test_выключенная_остановка_не_спрашивает(monkeypatch):
    monkeypatch.setattr(config, "HOLD", False)
    спрошено = []
    ctx = КликCtx(hold=lambda что: спрошено.append(что) or HOLD_RETRY)
    with pytest.raises(StepFailed):
        ctx.click(timeout=0, text="Войти")
    assert спрошено == []


def test_повторить_даёт_шагу_ещё_попытку():
    """Человек поправил экран руками — шаг обязан пройти, а не упасть."""
    ctx = КликCtx(найти_с_попытки=2, hold=lambda что: HOLD_RETRY)
    ctx.click(timeout=0, text="Войти")
    assert ctx.клики == 1
    assert ctx._holds == 1


def test_пропустить_идёт_дальше_без_падения():
    ctx = КликCtx(hold=lambda что: HOLD_SKIP)
    ctx.click(timeout=0, text="Войти")   # не бросает
    assert ctx.клики == 0


def test_уронить_ведёт_себя_как_обычное_падение():
    ctx = КликCtx(hold=lambda что: HOLD_DROP)
    with pytest.raises(StepFailed, match="не найден элемент"):
        ctx.click(timeout=0, text="Войти")


def test_непонятное_решение_роняет_задачу():
    ctx = КликCtx(hold=lambda что: "танцевать")
    with pytest.raises(StepFailed):
        ctx.click(timeout=0, text="Войти")


def test_сорванный_вопрос_роняет_задачу():
    """Спросить не удалось — исход должен быть прежним, а не зависанием."""
    def сломан(что):
        raise RuntimeError("очередь развалилась")

    ctx = КликCtx(hold=сломан)
    with pytest.raises(StepFailed):
        ctx.click(timeout=0, text="Войти")


def test_отмена_во_время_ожидания_не_превращается_в_падение():
    """Отмена будит остановленную задачу тем же событием, что решение.

    Без повторной проверки она читалась бы как «решение не пришло» и задача
    падала бы со StepFailed вместо CANCELLED.
    """
    состояние = {"отменено": False}

    def человек(что):
        состояние["отменено"] = True      # как будто нажали «отменить»
        return HOLD_DROP

    ctx = КликCtx(hold=человек, cancel_check=lambda: состояние["отменено"])
    with pytest.raises(Cancelled):
        ctx.click(timeout=0, text="Войти")


def test_потолок_остановок_на_задачу(monkeypatch):
    """«Повторить → снова промах» не должно длиться вечно."""
    monkeypatch.setattr(config, "HOLD_MAX_PER_JOB", 3)
    спрошено = []
    ctx = КликCtx(hold=lambda что: спрошено.append(что) or HOLD_RETRY)
    with pytest.raises(StepFailed):
        ctx.click(timeout=0, text="Войти")
    assert len(спрошено) == 3


# --------------------------------------------------- остальные шаги умеют то же

def test_пропустить_работает_у_якоря_экрана():
    ctx = DeviceContext("s", logger=lambda m: None, hold=lambda что: HOLD_SKIP)
    ctx._rescue = lambda: False
    ctx.escape = lambda ok: False
    ctx.exists = lambda timeout=2, **sel: False
    ctx.current_app = lambda: "com.other.app"
    ctx._screen_texts = lambda limit=5: ["Реклама"]
    ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0)


def test_якорь_на_повторить_пересверяет_экран():
    """Человек закрыл диалог руками — якорь должен увидеть свой экран."""
    состояние = {"свой": False}
    ctx = DeviceContext("s", logger=lambda m: None)
    ctx._hold = lambda что: состояние.__setitem__("свой", True) or HOLD_RETRY
    ctx._rescue = lambda: False
    ctx.escape = lambda ok: False
    ctx.exists = lambda timeout=2, **sel: состояние["свой"]
    ctx.current_app = lambda: "com.other.app"
    ctx._screen_texts = lambda limit=5: []
    ctx.expect_screen("login", any=[dict(text="Вход")], timeout=0)
    assert состояние["свой"] is True


def test_пропустить_работает_у_многослойной_цели(monkeypatch):
    from farm import resolve
    monkeypatch.setattr(resolve, "resolve", lambda *a, **kw: None)
    ctx = DeviceContext("s", logger=lambda m: None, hold=lambda что: HOLD_SKIP)
    ctx._settle = lambda: None
    ctx._rescue = lambda: False
    ctx.click_target(text=["Оплатить"], timeout=0)


# ------------------------------------------------------------------ очередь

@pytest.fixture
def задача():
    dv.deviations.clear()
    job = R.Job(id="j1", scenario_key="login", scenario_name="Вход",
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


def test_остановка_ждёт_ответа_и_возвращает_его(задача):
    решения = []

    def ответить():
        # ждём, пока задача правда встанет: иначе decide() опоздал бы
        for _ in range(200):
            if задача.status == R.HELD:
                break
            time.sleep(0.01)
        решения.append(R.runner.decide("j1", HOLD_SKIP))

    поток = threading.Thread(target=ответить)
    поток.start()
    assert R._hold(задача, "не найден элемент") == HOLD_SKIP
    поток.join()

    assert решения == [True]
    assert задача.status == R.RUNNING      # статус вернулся, устройство не отпущено
    assert задача.held_reason == ""
    assert "человек решил" in " ".join(задача.lines)


def test_остановка_поднимает_отклонение(задача):
    threading.Thread(target=lambda: (time.sleep(0.05),
                                     R.runner.decide("j1", HOLD_DROP))).start()
    R._hold(задача, "не найден элемент")
    (строка,) = dv.deviations.list()
    assert строка["kind"] == dv.HOLD
    assert строка["job_id"] == "j1"


def test_две_стоящие_задачи_не_сливаются_в_одну_строку(задача):
    """Слияние по причине здесь ломало бы смысл: решение нужно каждой задаче

    своё, и потерянная строка означает потерянное устройство.
    """
    вторая = R.Job(id="j2", scenario_key="login", scenario_name="Вход",
                   serial="emulator-5556", device_name="Pixel-2", params={})
    R.runner.jobs["j2"] = вторая
    R.runner.order.append("j2")
    try:
        R._record_hold(задача, "не найден элемент")
        R._record_hold(вторая, "не найден элемент")
        assert len(dv.deviations.list()) == 2
    finally:
        R.runner.jobs.pop("j2", None)
        R.runner.order.remove("j2")


def test_ожидание_истекает_и_роняет_задачу(задача, monkeypatch):
    monkeypatch.setattr(config, "HOLD_TIMEOUT", 0.1)
    assert R._hold(задача, "не найден элемент") == HOLD_DROP
    assert задача.status == R.RUNNING
    assert "никто не пришёл" in " ".join(задача.lines)


def test_потолок_стоящих_устройств(задача, monkeypatch):
    """Ночной прогон не должен встать весь: ждут только HOLD_MAX устройств."""
    monkeypatch.setattr(config, "HOLD_MAX", 1)
    monkeypatch.setattr(R.runner, "held", lambda: 1)
    assert R._hold(задача, "не найден элемент") == HOLD_DROP
    assert задача.status == R.RUNNING
    assert "не останавливаюсь" in " ".join(задача.lines)


def test_решение_опоздало(задача):
    """Задача уже не ждёт — «ок» соврало бы, что решение применилось."""
    assert R.runner.decide("j1", HOLD_SKIP) is False


def test_неизвестное_решение_отвергается(задача):
    with pytest.raises(ValueError):
        R.runner.decide("j1", "танцевать")


def test_стоящую_задачу_нельзя_удалить_из_журнала(задача):
    задача.status = R.HELD
    assert R.runner.delete("j1") is False
    assert R.runner.clear_finished() == 0


def test_отмена_будит_стоящую_задачу(задача):
    задача.status = R.HELD
    assert R.runner.cancel("j1") is True
    assert задача._decided.is_set()      # иначе проспала бы до HOLD_TIMEOUT


def test_стоящие_считаются_в_статистике(задача):
    задача.status = R.HELD
    assert R.runner.stats()[R.HELD] == 1
    assert R.runner.held() == 1


# ------------------------------------- гонка decide и конца ожидания в _hold

class _ТаймаутСобытие(threading.Event):
    """wait() всегда «истёк»; перед этим можно выполнить действие «человека»."""

    def __init__(self, до=None):
        super().__init__()
        self.до = до

    def wait(self, timeout=None):
        if self.до:
            self.до()
        return False


def test_decide_между_таймаутом_и_возвратом_статуса_не_обманывает(задача):
    """decide, пришедший уже ПОСЛЕ таймаута, обязан получить False.

    Раньше _hold читал решение и возвращал статус без замка: decide успевал
    в щель, отвечал UI «принято», а задача всё равно падала.
    """
    итог = []
    потоки = []
    ответил = threading.Event()

    def поздний():
        итог.append(R.runner.decide("j1", HOLD_RETRY, {"at": [0.1, 0.2]}))
        ответил.set()

    исходный = задача.add_line

    def add_line(s):
        исходный(s)
        if "никто не пришёл" in s:      # решение уже прочитано, статус ещё HELD
            t = threading.Thread(target=поздний)
            t.start()
            потоки.append(t)
            # с замком в _hold decide тут блокируется до выхода из _hold, поэтому
            # ждать его ответа здесь нельзя; часов не используем — ответ придёт
            # после возврата _hold, это проверяется ниже

    задача.add_line = add_line
    задача._decided = _ТаймаутСобытие()
    assert R._hold(задача, "не найден элемент") == HOLD_DROP
    assert ответил.wait(5)
    потоки[0].join(5)
    assert итог == [False]
    assert задача.target_patch is None and not задача._decided.is_set()
    assert задача.status == R.RUNNING


def test_decide_до_флипа_но_после_таймаута_событие_учитывается(задача):
    """Ответ, вставший в щель до чтения решения, не теряется: _hold его видит."""
    задача._decided = _ТаймаутСобытие(
        до=lambda: R.runner.decide("j1", HOLD_SKIP))
    # событие «не пришло», но decide уже записал решение — оно и возвращается
    assert R._hold(задача, "не найден элемент") == HOLD_SKIP
    assert задача.status == R.RUNNING and задача.target_patch is None
    assert not задача._decided.is_set()
    assert R.runner.decide("j1", HOLD_SKIP) is False


# ------------------------------------------------------------- шаг вслепую

def _blind_ctx(monkeypatch, answers, hold_on=True):
    from farm import config as cfg
    monkeypatch.setattr(cfg, "HOLD", hold_on)
    monkeypatch.setattr(cfg, "HOLD_BLIND", True)
    asked = []

    def hold(что, miss=""):
        asked.append(что)
        return answers.pop(0)

    ctx = DeviceContext("s", logger=lambda m: None, hold=hold)
    ctx.step_mark = lambda st: None
    monkeypatch.setattr(ctx, "_settle", lambda: None)
    return ctx, asked


def test_слабый_якорь_спрашивает_и_продолжает(monkeypatch):
    ctx, asked = _blind_ctx(monkeypatch, ["go"])
    monkeypatch.setattr(ctx, "_wait_features", lambda f, t: True)
    ctx.expect_screen("э", any=[{"resourceId": "com.android.systemui:id/status_bar"}])
    assert len(asked) == 1 and "системную панель" in asked[0]


def test_слабый_якорь_уронить_по_решению_человека(monkeypatch):
    ctx, _ = _blind_ctx(monkeypatch, ["drop"])
    with pytest.raises(StepFailed, match="остановил"):
        ctx.expect_screen("э", any=[{"resourceId": "com.android.systemui:id/status_bar"}])


def test_слабый_якорь_без_очереди_идёт_как_раньше(monkeypatch):
    ctx, asked = _blind_ctx(monkeypatch, [], hold_on=False)
    monkeypatch.setattr(ctx, "_wait_features", lambda f, t: True)
    ctx.expect_screen("э", any=[{"resourceId": "com.android.systemui:id/status_bar"}])
    assert asked == []


def _point_hit(monkeypatch):
    import types
    from farm import resolve
    hit = types.SimpleNamespace(layer="point", detail="", x=5, y=6)
    monkeypatch.setattr(resolve, "resolve", lambda ctx, **kw: hit)


def test_тап_вслепую_go_нажимает(monkeypatch):
    ctx, asked = _blind_ctx(monkeypatch, ["go"])
    _point_hit(monkeypatch)
    taps = []
    monkeypatch.setattr(ctx, "tap", lambda x, y: taps.append((x, y)))
    monkeypatch.setattr(ctx, "_deviation_shot", lambda n: "")
    ctx.click_target(sel=[{"text": "Х"}], at=(0.1, 0.2))
    assert taps == [(5, 6)] and "вслепую" in asked[0]


def test_тап_вслепую_skip_и_drop(monkeypatch):
    ctx, _ = _blind_ctx(monkeypatch, ["skip"])
    _point_hit(monkeypatch)
    taps = []
    monkeypatch.setattr(ctx, "tap", lambda x, y: taps.append(1))
    ctx.click_target(at=(0.1, 0.2))
    assert taps == []
    ctx2, _ = _blind_ctx(monkeypatch, ["drop"])
    monkeypatch.setattr(ctx2, "tap", lambda x, y: taps.append(1))
    with pytest.raises(StepFailed):
        ctx2.click_target(at=(0.1, 0.2))
    assert taps == []


def test_очередь_go_только_для_вслепую():
    job = R.Job(id="b1", scenario_key="k", scenario_name="К", serial="s",
                device_name="Д", params={})
    R.runner.jobs[job.id] = job
    job.status = R.HELD
    job.held_kind = ""
    with pytest.raises(ValueError, match="вслепую"):
        R.runner.decide(job.id, "go")
    job.held_kind = "blind"
    assert R.runner.decide(job.id, "go")
    R.runner.jobs.pop(job.id)
