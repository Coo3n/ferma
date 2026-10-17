"""Ветвление: развилка на прогоне, схема шага и сборка кода.

Устройство не нужно: экран — список «видимых» селекторов, как в остальных
тестах контекста.
"""
from datetime import date

import pytest

from farm import deviations as dv
from farm.context import DeviceContext
from farm.recorder import codegen, steps

ОНБОРДИНГ = {"онбординг": [dict(resourceId="com.app:id/skip")],
             "каталог": [dict(text="Каталог")]}


class РазвилкаCtx(DeviceContext):
    """ctx, у которого на экране заданный набор селекторов."""

    def __init__(self, экран, **kw):
        super().__init__("s", logger=lambda m: None, **kw)
        self.экран = list(экран)
        self.rescued = 0

    def exists(self, timeout=2, **sel):
        return sel in self.экран

    def _rescue(self):
        self.rescued += 1
        return False

    def current_app(self):
        return "com.app"

    def _screen_texts(self, limit=5):
        return ["Реклама", "Закрыть"]


@pytest.fixture(autouse=True)
def чистый_журнал():
    dv.deviations.clear()
    yield
    dv.deviations.clear()


# ------------------------------------------------------------------ прогон

def test_развилка_узнаёт_ветку():
    ctx = РазвилкаCtx([dict(text="Каталог")])
    assert ctx.which_screen(ОНБОРДИНГ, timeout=0) == "каталог"


def test_побеждает_первая_совпавшая():
    """Порядок значим: узкие ветки объявляют раньше широких."""
    ctx = РазвилкаCtx([dict(resourceId="com.app:id/skip"), dict(text="Каталог")])
    assert ctx.which_screen(ОНБОРДИНГ, timeout=0) == "онбординг"


def test_ветка_совпадает_по_любому_признаку():
    варианты = {"вход": [dict(text="Войти"), dict(text="Log in")]}
    ctx = РазвилкаCtx([dict(text="Log in")])
    assert ctx.which_screen(варианты, timeout=0) == "вход"


def test_ни_одна_не_совпала_не_роняет_прогон():
    """Развилка отвечает на «где я?», а не на «я обязан быть тут»."""
    ctx = РазвилкаCtx([dict(text="Чужой экран")])
    assert ctx.which_screen(ОНБОРДИНГ, timeout=0) == ""


def test_ни_одна_не_совпала_возвращает_default():
    ctx = РазвилкаCtx([])
    assert ctx.which_screen(ОНБОРДИНГ, timeout=0, default="прочее") == "прочее"


def test_стражам_дают_ход_прежде_чем_признать_ветку_незнакомой():
    """Перехватчик поверх экрана скрывает все ветки разом."""
    ctx = РазвилкаCtx([])
    ctx.which_screen(ОНБОРДИНГ, timeout=0)
    assert ctx.rescued == 1


def test_развилка_без_вариантов_это_ошибка_сценария():
    ctx = РазвилкаCtx([])
    with pytest.raises(ValueError):
        ctx.which_screen({}, timeout=0)


# ------------------------------------------------- отклонение о новой ветке

def test_незнакомая_ветка_записывается_отклонением():
    """Прогон доехал, в журнале задач ничего — узнать можно только отсюда."""
    ctx = РазвилкаCtx([], device_name="Pixel-1", job_id="j1",
                      scenario_key="login", scenario_name="Вход")
    ctx.which_screen(ОНБОРДИНГ, timeout=0)
    (строка,) = dv.deviations.list()
    assert строка["kind"] == dv.BRANCH
    assert "Реклама" in строка["title"]
    assert строка["job_id"] == "j1"


def test_совпавшая_ветка_отклонений_не_пишет():
    ctx = РазвилкаCtx([dict(text="Каталог")])
    ctx.which_screen(ОНБОРДИНГ, timeout=0)
    assert dv.deviations.list() == []


def test_report_false_молчит():
    """«Никакая» бывает штатным случаем — необязательный пейволл, которого

    обычно нет. Иначе каждый нормальный прогон писал бы отклонение.
    """
    ctx = РазвилкаCtx([])
    ctx.which_screen(ОНБОРДИНГ, timeout=0, report=False)
    assert dv.deviations.list() == []


def test_одна_непокрытая_развилка_это_одна_строка():
    """Двадцать устройств на одном и том же новом экране — одна строка."""
    for имя in ("Pixel-1", "Pixel-2"):
        РазвилкаCtx([], device_name=имя).which_screen(ОНБОРДИНГ, timeout=0)
    (строка,) = dv.deviations.list()
    assert строка["hits"] == 2


# ------------------------------------------------------------------ схема

ВЕТКИ = [{"name": "онбординг", "any": ['resourceId="com.app:id/skip"'],
          "run": "skip_onboarding"},
         {"name": "каталог", "any": ['text="Каталог"'], "run": ""}]


def test_шаг_branch_нормализуется():
    result = steps.normalize_step({"kind": "branch", "args": {"name": "после входа"},
                                   "arms": ВЕТКИ})
    assert result["arms"] == ВЕТКИ
    assert result["report"] is True


def test_branch_без_ветвей_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "branch", "args": {"name": "x"}, "arms": []})


def test_ветка_без_признаков_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "branch", "args": {"name": "x"},
                              "arms": [{"name": "a", "any": [], "run": ""}]})


def test_ветка_без_имени_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "branch", "args": {"name": "x"},
                              "arms": [{"name": " ", "any": ['text="a"']}]})


def test_две_ветки_с_одним_именем_отвергаются():
    """По имени выбирается блок — совпавшие имена означали бы потерянную ветку."""
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "branch", "args": {"name": "x"}, "arms": [
            {"name": "a", "any": ['text="1"']}, {"name": "a", "any": ['text="2"']}]})


def test_кривой_ключ_блока_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "branch", "args": {"name": "x"}, "arms": [
            {"name": "a", "any": ['text="1"'], "run": "../побег"}]})


def test_число_ветвей_ограничено():
    много = [{"name": f"в{i}", "any": [f'text="{i}"']} for i in range(9)]
    result = steps.normalize_step({"kind": "branch", "args": {"name": "x"},
                                   "arms": много})
    assert len(result["arms"]) == steps.ARMS_MAX


def test_поле_arms_запрещено_другим_шагам():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "key", "args": {"name": "back"},
                              "arms": ВЕТКИ})


# ------------------------------------------------------------------ код

def МЕТА():
    return {"name": "Демо", "description": "", "watch_popups": False, "human": False}


def собрать(шаг):
    return codegen.render(МЕТА(), {}, [steps.normalize_step(шаг)], date(2026, 9, 14))


def test_код_развилки():
    src = собрать({"kind": "branch", "args": {"name": "после входа", "timeout": 8},
                   "arms": ВЕТКИ})
    assert 'ветка = ctx.which_screen({' in src
    assert '    "онбординг": [dict(resourceId="com.app:id/skip")],' in src
    assert '    "каталог": [dict(text="Каталог")],' in src
    assert '}, timeout=8)' in src
    assert 'if ветка == "онбординг":\n        ctx.run("skip_onboarding")' in src
    # у ветки без блока условия нет: делать на ней нечего
    assert 'if ветка == "каталог"' not in src


def test_код_развилки_компилируется():
    """Сгенерированный файл обязан импортироваться — иначе сценарий мёртв."""
    src = собрать({"kind": "branch", "args": {"name": "x"},
                   "arms": [{"name": 'с "кавычками"', "any": ['text="Ок"'],
                             "run": "blk"}]})
    compile(src, "<gen>", "exec")


def test_report_false_попадает_в_код():
    src = собрать({"kind": "branch", "args": {"name": "x"}, "arms": ВЕТКИ,
                   "report": False})
    assert "report=False" in src


def test_метка_вешается_на_первую_строку_развилки():
    src = собрать({"kind": "branch", "args": {"name": "x"}, "arms": ВЕТКИ,
                   "note": "A/B онбординг"})
    assert "ctx.which_screen({  # A/B онбординг" in src
