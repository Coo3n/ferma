"""«Листать, пока не найдётся» у шага нажатия — по выбору, по умолчанию выключено.

Владелец: «не всегда нужно; человек не должен удивляться „что это“». Поэтому
листание включается только полем шага `scroll`, каждое листание пишется в
журнал словами, а промах говорит, сколько раз листали.
"""
import pytest

from farm.context import StepFailed
from farm.recorder import codegen, steps
from test_scope import Ctx, _post

PAGE_END = '</node></node></hierarchy>'


def page(*authors, like=True):
    body = "".join(_post(i, a) for i, a in enumerate(authors))
    if not like:   # имя автора видно, а лайк под ним ещё за краем экрана
        body = body.replace('content-desc="Нравится" resource-id="app:id/like"',
                            'content-desc="" resource-id="app:id/cut"')
    return ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1000,2000]">'
            '<node class="android.widget.ScrollView" resource-id="app:id/feed" '
            'bounds="[0,0][1000,1900]">' + body + PAGE_END)


class Feed(Ctx):
    """Лента: каждое листание вниз — следующая страница, вверх — предыдущая."""

    def __init__(self, pages, **kw):
        super().__init__(**kw)
        self.pages = pages
        self.at = 0
        self.swipes = []

    def dump_hierarchy(self):
        return self.pages[self.at]

    def swipe(self, x1, y1, x2, y2, duration=0.25):
        self.swipes.append("down" if y2 < y1 else "up")
        self.at = max(0, min(len(self.pages) - 1, self.at + (1 if y2 < y1 else -1)))

    def sleep(self, seconds):
        pass


FEED3 = [page("Анна", "Олег"), page("Олег", "Мария"), page("Мария", "Иван Петров")]


def test_рядом_с_листает_вниз_пока_не_найдёт():
    ctx = Feed(FEED3)
    ctx.click(resourceId="app:id/like", near={"text": "Иван Петров"},
              scroll_until=("down", 5), timeout=0)
    assert ctx.swipes == ["down", "down"]
    assert ctx.taps == [(0.07, 0.57)]
    assert "листаю вниз (1 из 5): ищу «like» рядом с «Иван Петров»" in ctx.lines
    assert "листаю вниз (2 из 5): ищу «like» рядом с «Иван Петров»" in ctx.lines


def test_ориентир_есть_а_цели_нет_листает_дальше():
    """«Рядом с» — ориентир и цель на экране вместе, а не ориентир один."""
    ctx = Feed([page("Анна", "Иван Петров", like=False), page("Анна", "Иван Петров")])
    ctx.click_any({"resourceId": "app:id/like"}, near={"text": "Иван Петров"},
                  scroll_until=("down", 3), timeout=0)
    assert ctx.swipes == ["down"] and ctx.taps == [(0.07, 0.57)]


def test_не_нашлось_за_n_раз_обычный_промах_со_счётом():
    ctx = Feed(FEED3)
    with pytest.raises(StepFailed) as e:
        ctx.click(resourceId="app:id/like", near={"text": "Пётр"},
                  scroll_until=("down", 3), timeout=0)
    assert ctx.swipes == ["down"] * 3 and ctx.taps == []
    assert "не найден ориентир" in str(e.value)
    assert "пролистал вниз 3 раза" in str(e.value)


def test_вверх():
    ctx = Feed(FEED3)
    ctx.at = 2
    ctx.click(resourceId="app:id/like", near={"text": "Анна"}, scroll_until=("up", 4), timeout=0)
    assert ctx.swipes == ["up", "up"] and ctx.taps == [(0.07, 0.27)]
    assert any(line.startswith("листаю вверх (1 из 4)") for line in ctx.lines)


def test_без_поля_не_листает():
    ctx = Feed(FEED3)
    with pytest.raises(StepFailed) as e:
        ctx.click(resourceId="app:id/like", near={"text": "Иван Петров"}, timeout=0)
    assert ctx.swipes == [] and "пролистал" not in str(e.value)


def test_цель_сразу_на_экране_не_листает():
    ctx = Feed(FEED3)
    ctx.click(resourceId="app:id/like", near={"text": "Олег"}, scroll_until=("down", 5),
              timeout=0)
    assert ctx.swipes == [] and not any("листаю" in line for line in ctx.lines)


def test_слои_с_листанием_текст_находит_после_свайпа():
    ctx = Feed(FEED3)
    ctx.click_target(sel=[{"text": "нет"}], text=["Нравится"], near={"text": "Иван Петров"},
                     scroll_until=("down", 5), timeout=0)
    assert ctx.swipes == ["down", "down"] and ctx.taps == [(0.07, 0.57)]
    assert "листаю вниз (1 из 5): ищу «Нравится» рядом с «Иван Петров»" in ctx.lines


def test_с_листанием_тапа_по_старой_точке_нет():
    """После свайпа «место, где было» — уже чужой пост: вслепую не жмём."""
    ctx = U2Feed(FEED3, "нет такого")
    with pytest.raises(StepFailed) as e:
        ctx.click_target(sel=[{"text": "нет"}], at=(0.5, 0.5), scroll_until=("down", 2),
                         timeout=0)
    assert ctx.taps == [] and ctx.swipes == ["down", "down"]
    assert "пролистал вниз 2 раза" in str(e.value)


class U2Feed(Feed):
    """Без места цель ищется через u2: «видна» на странице с нужным автором."""

    def __init__(self, pages, want, **kw):
        super().__init__(pages, **kw)
        self.want = want
        self.clicked = []

    def find(self, timeout=10, **selector):
        if self.want not in self.pages[self.at]:
            return None
        ctx = self

        class El:
            def click(self):
                ctx.clicked.append(ctx.at)
        return El()

    def _scroll_to(self, **selector):
        raise AssertionError("с листанием шага u2 сам не прокручивает")


def test_без_места_u2_тоже_листает():
    ctx = U2Feed(FEED3, "Иван Петров")
    ctx.click(text="Иван Петров", scroll_until=("down", 5), timeout=0)
    assert ctx.swipes == ["down", "down"] and ctx.clicked == [2]
    assert "листаю вниз (1 из 5): ищу «Иван Петров»" in ctx.lines


def test_цепочка_без_места_листает():
    ctx = U2Feed(FEED3, "Мария")
    ctx.click_any({"text": "Мария"}, {"description": "Мария"}, scroll_until=("down", 5),
                  timeout=0)
    assert ctx.swipes == ["down"] and ctx.clicked == [1]


def test_кривое_значение_листания_отвергается():
    ctx = Feed(FEED3)
    for bad in (("left", 3), ("down", 0), ("down", 11), "down"):
        with pytest.raises(ValueError):
            ctx.click(resourceId="app:id/like", scroll_until=bad, timeout=0)


# ------------------------------------------------ формат рецепта и кодоген

def click(**extra):
    raw = {"kind": "click", "selector": {"call": "click", "args": 'resourceId="app:id/like"'}}
    raw.update(extra)
    return raw


def test_поле_scroll_проходит_проверку():
    st = steps.normalize_step(click(scroll={"dir": "down", "max": 5}))
    assert st["scroll"] == {"dir": "down", "max": 5}
    assert steps.normalize_step(click(scroll={"dir": "up", "max": "3"}))["scroll"] == \
        {"dir": "up", "max": 3}
    assert "scroll" not in steps.normalize_step(click())
    assert "scroll" not in steps.normalize_step(click(scroll=None))


@pytest.mark.parametrize("bad", [
    {"dir": "left", "max": 3}, {"dir": "down", "max": 0}, {"dir": "down", "max": 11},
    {"dir": "down"}, "down", {"dir": "down", "max": 2, "лишнее": 1}, {"dir": "down", "max": True},
])
def test_плохое_поле_scroll_отвергается(bad):
    with pytest.raises(steps.StepError):
        steps.normalize_step(click(scroll=bad))


def test_scroll_только_у_click():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "tap", "args": {"x": 0.1, "y": 0.1},
                              "scroll": {"dir": "down", "max": 2}})


def _line(step):
    src = codegen.render({"name": "n", "watch_popups": False}, {}, [steps.normalize_step(step)])
    compile(src, "x.py", "exec")
    return src.strip().splitlines()[-1].strip()


def test_кодоген_хвост_листания_у_всех_трёх_вызовов():
    sc = {"dir": "down", "max": 5}
    assert _line(click(scroll=sc)) == \
        'ctx.click(resourceId="app:id/like", scroll_until=("down", 5))'
    assert _line(click(scroll=sc, near='text="Иван"')) == \
        'ctx.click(resourceId="app:id/like", near=dict(text="Иван"), scroll_until=("down", 5))'
    raw = click(scroll={"dir": "up", "max": 2})
    raw["selector"]["fallbacks"] = ['description="Нравится"']
    assert _line(raw) == ('ctx.click_any(dict(resourceId="app:id/like"), '
                          'dict(description="Нравится"), scroll_until=("up", 2))')
    raw["texts"] = ["Нравится"]
    assert _line(raw).endswith('text=["Нравится"], scroll_until=("up", 2))')


def test_схема_знает_листание():
    assert steps.schema()["click_scroll"]["max"] == 10
