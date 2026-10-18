"""«Внутри родителя» и «рядом с элементом» у шага click.

Владелец: «лайков в ленте три одинаковых — нужен тот, что под постом Ивана».
Номер среди похожих (instance) ломается, как только лента сдвинется; признак
«рядом с «Иван Петров»» переживает сдвиг.
"""
import pytest

from farm.context import DeviceContext, HOLD_RETRY, StepFailed, normalize_target
from farm.recorder import codegen, steps
from farm.ui import scope, tree

W, H = 1000, 2000


def _post(i, author, extra=""):
    y = 100 + i * 600
    return (f'<node class="android.widget.LinearLayout" resource-id="app:id/post" '
            f'bounds="[0,{y}][1000,{y + 500}]">'
            f'<node class="android.widget.TextView" text="{author}" '
            f'resource-id="app:id/author" bounds="[20,{y + 10}][500,{y + 60}]"/>'
            f'<node class="android.widget.TextView" text="{i + 3} ч" '
            f'bounds="[520,{y + 10}][700,{y + 60}]"/>'
            f'<node class="android.widget.ImageView" content-desc="Нравится" '
            f'resource-id="app:id/like" clickable="true" '
            f'bounds="[20,{y + 400}][120,{y + 480}]"/>{extra}</node>')


FEED = ('<hierarchy><node class="android.widget.FrameLayout" bounds="[0,0][1000,2000]">'
        '<node class="android.widget.ScrollView" resource-id="app:id/feed" '
        'bounds="[0,0][1000,1900]">'
        + _post(0, "Анна") + _post(1, "Иван Петров") + _post(2, "Олег")
        + '</node>'
        '<node class="android.widget.LinearLayout" resource-id="app:id/stories" '
        'bounds="[0,1900][1000,2000]">'
        '<node class="android.widget.ImageView" content-desc="Нравится" '
        'resource-id="app:id/like" clickable="true" bounds="[10,1910][90,1990]"/>'
        '</node></node></hierarchy>')


def nodes():
    return tree.parse(FEED, W, H)


def likes(ns):
    return [n for n in ns if n.resource_id == "app:id/like"]


# ------------------------------------------------ чистая логика выбора

def test_разбор_аргументов_селектора():
    assert scope.parse_args('resourceId="a:id/x", instance=1') == {
        "resourceId": "a:id/x", "instance": 1}
    assert scope.parse_args('text="Вой\\"ти"') == {"text": 'Вой"ти'}
    with pytest.raises(scope.ScopeError):
        scope.parse_args("__import__('os')")


def test_совпадения_по_ключам():
    ns = nodes()
    assert len(scope.find(ns, {"resourceId": "app:id/like"})) == 4
    assert len(scope.find(ns, {"description": "Нравится", "instance": 2})) == 1
    assert scope.find(ns, {"textContains": "Петров"})[0].text == "Иван Петров"
    assert scope.find(ns, {"resourceIdMatches": ".*/like$"})[0] is likes(ns)[0]
    with pytest.raises(scope.ScopeError):
        scope.find(ns, {"index": 1})


def test_рядом_с_выбирает_лайк_под_нужным_постом():
    ns = nodes()
    node, miss = scope.pick(ns, {"resourceId": "app:id/like"}, near={"text": "Иван Петров"})
    assert miss == "" and node is likes(ns)[1]


def test_внутри_ищет_только_в_контейнере():
    ns = nodes()
    node, miss = scope.pick(ns, {"description": "Нравится"},
                            within={"resourceId": "app:id/stories"})
    assert miss == "" and node is likes(ns)[3]


def test_внутри_и_номер_считается_среди_вложенных():
    ns = nodes()
    node, _ = scope.pick(ns, {"resourceId": "app:id/like", "instance": 1},
                         within={"resourceId": "app:id/feed"})
    assert node is likes(ns)[1]


def test_причина_промаха():
    ns = nodes()
    assert scope.pick(ns, {"resourceId": "app:id/like"}, within={"text": "нет"}) == (None, "within")
    assert scope.pick(ns, {"resourceId": "app:id/like"}, near={"text": "нет"}) == (None, "near")
    assert scope.pick(ns, {"text": "нет"}, near={"text": "Олег"}) == (None, "target")
    # контейнер есть, а цели в нём нет
    assert scope.pick(ns, {"text": "Анна"}, within={"resourceId": "app:id/stories"}) == (None, "target")


def test_равная_глубина_решается_расстоянием():
    """Ориентир вне постов (общий предок — лента): ближе по экрану — тот и нажат."""
    ns = nodes()
    node, _ = scope.pick(ns, {"resourceId": "app:id/author"}, near={"resourceId": "app:id/stories"})
    assert node.text == "Олег"


# ------------------------------------------------ формат рецепта

def click(**extra):
    raw = {"kind": "click", "selector": {"call": "click", "args": 'resourceId="app:id/like"'}}
    raw.update(extra)
    return raw


def test_старый_шаг_без_новых_полей_не_меняется():
    step = steps.normalize_step(click())
    assert "within" not in step and "near" not in step


def test_рядом_и_внутри_проходят_проверку():
    assert steps.normalize_step(click(near='text="Иван Петров"'))["near"] == 'text="Иван Петров"'
    assert steps.normalize_step(click(within='resourceId="app:id/post"'))["within"] == \
        'resourceId="app:id/post"'


@pytest.mark.parametrize("extra", [
    {"near": 'text="12:45"'},                       # время — завтра другое
    {"within": 'description="125"'},                # счётчик
    {"near": 'text="a", within="b"'},               # ключ не из списка
    {"near": 'textMatches=".*"'},                   # регулярка
    {"near": 'text="' + "я" * 300 + '"'},           # слишком длинно
    {"near": "__import__('os')"},
    {"near": 'text="a"', "within": 'resourceId="b"'},  # не больше одного
    {"near": 'instance=1'},                          # номер — не ориентир
])
def test_плохие_ориентиры_отвергаются(extra):
    with pytest.raises(steps.StepError):
        steps.normalize_step(click(**extra))


def test_поле_только_у_click():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "tap", "args": {"x": 0.1, "y": 0.1}, "near": 'text="a"'})


def test_с_ориентиром_ключи_цели_должны_быть_понятны_ферме():
    raw = click(near='text="Иван"')
    raw["selector"]["fallbacks"] = ['index=2']
    with pytest.raises(steps.StepError):
        steps.normalize_step(raw)


def test_схема_знает_новые_поля():
    assert "near" in steps.schema()["click_scope"] and "within" in steps.schema()["click_scope"]


# ------------------------------------------------ кодоген

def _line(step):
    src = codegen.render({"name": "n", "watch_popups": False}, {}, [steps.normalize_step(step)])
    line = src.strip().splitlines()[-1].strip()
    compile(src, "x.py", "exec")
    return line


def test_кодоген_рядом_с():
    assert _line(click(near='text="Иван"')) == \
        'ctx.click(resourceId="app:id/like", near=dict(text="Иван"))'


def test_кодоген_внутри_с_запасными_и_слоями():
    raw = click(within='resourceId="app:id/post"', texts=["Нравится"], point=[0.1, 0.2])
    raw["selector"]["fallbacks"] = ['description="Нравится"']
    assert _line(raw) == (
        'ctx.click_target(sel=[dict(resourceId="app:id/like"), dict(description="Нравится")], '
        'text=["Нравится"], at=(0.1, 0.2), within=dict(resourceId="app:id/post"))')
    raw.pop("texts"), raw.pop("point")
    assert _line(raw) == ('ctx.click_any(dict(resourceId="app:id/like"), '
                          'dict(description="Нравится"), within=dict(resourceId="app:id/post"))')


def test_карта_строк_не_съезжает():
    st = [steps.normalize_step(click(near='text="Иван"')), steps.normalize_step(click())]
    src, line_map = codegen.render_mapped({"name": "n"}, {}, st)
    lines = src.splitlines()
    assert sorted(line_map.values()) == [0, 1]
    assert "near=" in lines[[k for k, v in line_map.items() if v == 0][0] - 1]


# ------------------------------------------------ прогон

class Ctx(DeviceContext):
    def __init__(self, xml=FEED, **kw):
        super().__init__("s", logger=lambda m: None, **kw)
        self.xml = xml
        self.taps = []
        self.lines = []
        self._logger = self.lines.append

    def _settle(self):
        pass

    def _rescue(self):
        return False

    @property
    def size(self):
        return (W, H)

    def dump_hierarchy(self):
        return self.xml

    def tap(self, x, y):
        self.taps.append((round(x, 3), round(y, 3)))

    def find(self, timeout=10, **selector):
        raise AssertionError("с ориентиром поиск идёт по дампу, не через u2")


LIKE2 = (0.07, 0.57)    # центр лайка под постом Ивана


def test_click_рядом_с():
    ctx = Ctx()
    ctx.click(resourceId="app:id/like", near={"text": "Иван Петров"}, timeout=0)
    assert ctx.taps == [LIKE2]


def test_click_any_применяет_ориентир_к_каждому_варианту():
    ctx = Ctx()
    ctx.click_any({"text": "нет такого"}, {"description": "Нравится"},
                  within={"resourceId": "app:id/stories"}, timeout=0)
    assert ctx.taps == [(0.05, 0.975)]


def test_click_target_с_ориентиром():
    ctx = Ctx()
    ctx.click_target(sel=[{"resourceId": "app:id/like"}], text=["Нравится"],
                     near={"text": "Иван Петров"}, timeout=0)
    assert ctx.taps == [LIKE2]


def test_нет_ориентира_понятная_ошибка():
    ctx = Ctx()
    with pytest.raises(StepFailed) as e:
        ctx.click(resourceId="app:id/like", near={"text": "Мария"}, timeout=0)
    assert "не найден ориентир" in str(e.value) and "Мария" in str(e.value)
    with pytest.raises(StepFailed) as e:
        ctx.click_any({"resourceId": "app:id/like"}, within={"resourceId": "app:id/nope"}, timeout=0)
    assert "не найдено место поиска" in str(e.value)
    with pytest.raises(StepFailed) as e:
        ctx.click(text="Анна", within={"resourceId": "app:id/stories"}, timeout=0)
    assert "не найден элемент" in str(e.value) and "внутри" in str(e.value)


def test_повтор_после_остановки_ищет_снова():
    ответы = [HOLD_RETRY]
    ctx = Ctx(hold=lambda что: ответы.pop())
    xml = [FEED.replace("Иван Петров", "Иван")]
    ctx.dump_hierarchy = lambda: xml[0]
    orig = ctx._stuck

    def stuck(*a, **kw):
        xml[0] = FEED
        return orig(*a, **kw)

    ctx._stuck = stuck
    ctx.click(resourceId="app:id/like", near={"text": "Иван Петров"}, timeout=0)
    assert ctx.taps == [LIKE2]


def test_патч_цели_несёт_ориентир():
    patch = normalize_target({"sel": [{"text": "x"}], "near": {"text": "Иван"}, "within": None})
    assert patch == {"sel": [{"text": "x"}], "near": {"text": "Иван"}, "within": None}
    with pytest.raises(ValueError):
        normalize_target({"sel": [{"text": "x"}], "near": {"textMatches": ".*"}})
    with pytest.raises(ValueError):
        normalize_target({"sel": [{"text": "x"}], "near": "text"})


def test_патч_цели_меняет_ориентир_на_лету():
    патчи = [{"near": {"text": "Иван Петров"}}]
    ctx = Ctx(hold=lambda что, miss="": HOLD_RETRY,
              take_target_patch=lambda: патчи.pop() if патчи else None)
    ctx.click_target(sel=[{"resourceId": "app:id/like"}], near={"text": "Мария"}, timeout=0)
    assert ctx.taps == [LIKE2]
