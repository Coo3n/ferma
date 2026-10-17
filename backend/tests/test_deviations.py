"""Отклонения от сценария: слияние, прочтение, слепок обойдённой преграды.

Устройство не нужно: журнал отклонений — чистая память, а ctx фейковый.
"""
import json

import pytest

from farm import config, deviations as dv, obstacle
from farm.deviations import deviations
from farm.context import DeviceContext


@pytest.fixture(autouse=True)
def чистый_журнал():
    deviations.clear()
    yield
    deviations.clear()


def записать(**kw):
    основа = dict(kind=dv.FAIL, title="не найден элемент",
                  scenario_key="flow", signature="не найден элемент")
    основа.update(kw)
    return deviations.record(**основа)


# ------------------------------------------------------------------ журнал

def test_отклонение_попадает_в_список_и_в_счётчик():
    записать(device_name="Pixel-1")
    assert deviations.unseen() == 1
    строки = deviations.list()
    assert len(строки) == 1
    assert строки[0]["devices"] == ["Pixel-1"]
    assert строки[0]["hits"] == 1


def test_одинаковые_отклонения_сливаются_в_одну_строку():
    """Двадцать устройств об одну стену — это одна строка со счётчиком:

    чинится она одним отводом, а двадцать строк только спрячут остальное.
    """
    записать(device_name="Pixel-1")
    записать(device_name="Pixel-2")
    строки = deviations.list()
    assert len(строки) == 1
    assert строки[0]["hits"] == 2
    assert строки[0]["devices"] == ["Pixel-1", "Pixel-2"]
    assert deviations.unseen() == 1


def test_список_устройств_не_растёт_бесконечно():
    for i in range(dv.MAX_DEVICES + 5):
        записать(device_name=f"Pixel-{i}")
    строка = deviations.list()[0]
    assert строка["hits"] == dv.MAX_DEVICES + 5
    assert len(строка["devices"]) == dv.MAX_DEVICES


def test_разные_подписи_не_сливаются():
    записать(signature="не найден «Войти»")
    записать(signature="не найден «Оплатить»")
    assert len(deviations.list()) == 2


def test_после_прочтения_то_же_отклонение_поднимается_заново():
    """Прочитано означает «видел и разобрался». Если случилось снова — это

    новость, а не прибавка к счётчику закрытого отклонения.
    """
    записать()
    deviations.mark_seen()
    записать()
    строки = deviations.list()
    assert len(строки) == 2
    assert deviations.unseen() == 1


def test_слепок_последней_задачи_вытесняет_прежний():
    """Артефакты старых задач чистят — кнопка обучения должна вести к свежим."""
    записать(job_id="j1", obstacle_file="obstacle.json")
    записать(job_id="j2", obstacle_file="obstacle.json")
    строка = deviations.list()[0]
    assert строка["job_id"] == "j2"


def test_новое_отклонение_хранит_кадр_промах_и_шаг():
    записать(job_id="j1", shot="99_failure.jpg",
             miss='{"sel": [], "at": [1, 2]}', step_index=3)
    строка = deviations.list()[0]
    assert строка["shot"] == "99_failure.jpg"
    assert строка["miss"] == '{"sel": [], "at": [1, 2]}'
    assert строка["step_index"] == 3


def test_без_кадра_поля_по_умолчанию_пустые():
    """step_index == -1 значит «шаг неизвестен» (сценарий написан руками)."""
    строка = записать().to_dict()
    assert строка["shot"] == ""
    assert строка["miss"] == ""
    assert строка["step_index"] == -1


def test_кадр_последней_задачи_вытесняет_прежний():
    """Как и слепок: артефакты старых задач чистят, кадр должен быть свежим."""
    записать(job_id="j1", shot="a.jpg", miss="m1", step_index=1)
    записать(job_id="j2", shot="b.jpg", miss="m2", step_index=2)
    строка = deviations.list()[0]
    assert (строка["shot"], строка["miss"], строка["step_index"]) == ("b.jpg", "m2", 2)
    assert строка["job_id"] == "j2"


def test_пустой_кадр_не_затирает_прежний():
    записать(job_id="j1", shot="a.jpg", miss="m1", step_index=1)
    записать(job_id="j2")
    строка = deviations.list()[0]
    assert (строка["shot"], строка["miss"], строка["step_index"]) == ("a.jpg", "m1", 1)
    assert строка["job_id"] == "j1"


def test_прочтение_одной_не_трогает_остальные():
    первая = записать(signature="раз")
    записать(signature="два")
    assert deviations.mark_seen(первая.id) == 1
    assert deviations.unseen() == 1


def test_удаление_и_очистка():
    строка = записать()
    assert deviations.delete(строка.id) is True
    assert deviations.delete(строка.id) is False
    записать(signature="ещё")
    assert deviations.clear() == 1
    assert deviations.list() == []


def test_журнал_не_растёт_выше_потолка(monkeypatch):
    monkeypatch.setattr(config, "DEVIATION_HISTORY", 3)
    журнал = dv.DeviationLog()
    for i in range(10):
        журнал.record(kind=dv.FAIL, title=f"беда {i}",
                      signature=f"беда {i}")
    assert len(журнал.list(limit=99)) == 3


def test_неизвестный_вид_отвергается():
    with pytest.raises(ValueError):
        deviations.record(kind="танцевать", title="что-то")


# ---------------------------------------------------- слепок при удачном выходе

class ВыходCtx(DeviceContext):
    """ctx, который выбирается с незнакомого экрана с первой попытки."""

    def __init__(self, art_dir, освободиться=True):
        super().__init__("s", logger=lambda m: None, artifacts_dir=art_dir,
                         device_name="Pixel-1", job_id="j1",
                         scenario_key="flow", scenario_name="Мой сценарий")
        self.освободиться = освободиться
        self.попытки = 0

    def _obstacle_snapshot(self):
        return {"package": "com.app", "texts": ["Смотреть рекламу"],
                "candidates": [{"selector": {"textContains": "Смотреть рекламу"},
                                "label": "по тексту: «Смотреть рекламу»"}]}

    def key(self, name):
        self.попытки += 1

    def click_if_exists(self, timeout=2, **selector):
        self.попытки += 1
        return False

    def exists(self, timeout=2, **selector):
        return self.освободиться


def test_удачный_выход_оставляет_слепок_и_запись(tmp_path):
    ctx = ВыходCtx(tmp_path)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is True

    файл = tmp_path / "obstacle_escaped_01.json"
    слепок = json.loads(файл.read_text("utf-8"))
    assert слепок["escaped"] is True
    assert слепок["texts"] == ["Смотреть рекламу"]

    строка = deviations.list()[0]
    assert строка["kind"] == dv.ESCAPE
    assert строка["obstacle_file"] == "obstacle_escaped_01.json"
    assert строка["job_id"] == "j1"
    assert строка["scenario_name"] == "Мой сценарий"


def test_неудачный_выход_слепок_не_пишет(tmp_path):
    """Тот же экран снимет падение задачи: два слепка одного экрана только

    раздували бы карту отводов.
    """
    ctx = ВыходCtx(tmp_path, освободиться=False)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is False
    assert list(tmp_path.glob("obstacle*.json")) == []
    assert deviations.list() == []


def test_несколько_преград_за_прогон_не_перетирают_друг_друга(tmp_path):
    ctx = ВыходCtx(tmp_path)
    ctx.escape(lambda: ctx.exists(text="цель"))
    ctx.escape(lambda: ctx.exists(text="цель"))
    assert sorted(p.name for p in tmp_path.glob("obstacle*.json")) == [
        "obstacle_escaped_01.json", "obstacle_escaped_02.json"]


def test_выключенный_выход_ничего_не_снимает(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ESCAPE", False)
    ctx = ВыходCtx(tmp_path)
    assert ctx.escape(lambda: ctx.exists(text="цель")) is False
    assert list(tmp_path.glob("obstacle*.json")) == []


# ------------------------------------------------- карта отводов различает их

def test_карта_считает_обойдённые_и_упавшие_отдельно():
    """Преграда, которую обходят вслепую, по журналу задач не видна вовсе:

    прогоны доезжают. В карте отводов она обязана быть — с пометкой, что
    именно с ней происходит.
    """
    слепок = {"package": "com.app", "texts": ["Реклама"],
              "candidates": [{"selector": {"textContains": "Реклама"},
                              "label": "по тексту"}]}
    преграды = [dict(слепок, escaped=True), dict(слепок, escaped=True),
                dict(слепок)]
    (строка,) = obstacle.uncovered(преграды, [])
    assert строка["hits"] == 3
    assert строка["escapes"] == 2
    assert строка["fails"] == 1


def test_слияние_по_полям_последнее_непустое_побеждает():
    log = dv.DeviationLog()
    a = log.record(kind=dv.LAYER, title="t", signature="s", job_id="j1",
                   shot="a.jpg", miss="{1}", step_index=3, obstacle_file="o1")
    log.record(kind=dv.LAYER, title="t", signature="s", job_id="j2", miss="{2}")
    assert (a.shot, a.miss, a.step_index, a.obstacle_file, a.job_id) == \
        ("a.jpg", "{2}", 3, "o1", "j1")          # job_id не за miss
    log.record(kind=dv.LAYER, title="t", signature="s", job_id="j3", shot="b.jpg")
    assert (a.shot, a.miss, a.job_id) == ("b.jpg", "{2}", "j3")
    log.record(kind=dv.LAYER, title="t", signature="s", job_id="j4",
               step_index=7, obstacle_file="o2")
    assert (a.step_index, a.obstacle_file, a.job_id, a.shot) == (7, "o2", "j4", "b.jpg")
    assert a.hits == 4
