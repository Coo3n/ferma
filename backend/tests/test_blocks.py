"""Сценарий как переиспользуемый блок: ctx.run(key). Устройство не нужно."""
import pytest

from farm import scenarios
from farm.context import DeviceContext, StepFailed


class ФейкМодуль:
    def __init__(self, fn):
        self.run = fn


def подсунуть(monkeypatch, **блоки):
    """Подменяем реестр сценариев: ключ -> функция run(ctx)."""
    реестр = {
        key: scenarios.Scenario(
            key=key, name=key, description="", params=params,
            path=f"{key}.py", mtime=0, module=ФейкМодуль(fn))
        for key, (fn, params) in блоки.items()
    }
    monkeypatch.setattr(scenarios, "get", lambda k: реестр.get(k))
    return реестр


def ctx_(lines=None):
    return DeviceContext("s", logger=(lines.append if lines is not None else (lambda m: None)))


def test_блок_выполняется(monkeypatch):
    следы = []
    подсунуть(monkeypatch, login=(lambda ctx: следы.append("login"), {}))
    ctx_().run("login")
    assert следы == ["login"]


def test_параметры_передаются_и_восстанавливаются(monkeypatch):
    видел = {}
    подсунуть(monkeypatch, login=(
        lambda ctx: видел.update(ctx.params),
        {"user": {"label": "Юзер", "default": "по умолчанию"}}))
    ctx = ctx_()
    ctx.params = {"внешний": 1}
    ctx.run("login", user="петя")
    assert видел["user"] == "петя"
    assert ctx.params == {"внешний": 1}, "параметры вызывающего затёрты"


def test_значение_по_умолчанию_подставляется(monkeypatch):
    видел = {}
    подсунуть(monkeypatch, login=(
        lambda ctx: видел.update(ctx.params),
        {"user": {"label": "Юзер", "default": "аноним"}}))
    ctx_().run("login")
    assert видел["user"] == "аноним"


def test_прямая_рекурсия_ловится(monkeypatch):
    подсунуть(monkeypatch, loop=(lambda ctx: ctx.run("loop"), {}))
    with pytest.raises(StepFailed, match="сам себя"):
        ctx_().run("loop")


def test_взаимная_рекурсия_ловится(monkeypatch):
    подсунуть(monkeypatch,
              a=(lambda ctx: ctx.run("b"), {}),
              b=(lambda ctx: ctx.run("a"), {}))
    with pytest.raises(StepFailed, match="сам себя"):
        ctx_().run("a")


def test_слишком_глубокая_вложенность_ловится(monkeypatch):
    # каждый блок зовёт следующий: b0 -> b1 -> ... — рекурсии нет, есть глубина
    блоки = {f"b{i}": ((lambda n: lambda ctx: ctx.run(f"b{n + 1}"))(i), {})
             for i in range(12)}
    подсунуть(monkeypatch, **блоки)
    with pytest.raises(StepFailed, match="вложенность"):
        ctx_().run("b0")


def test_пропавший_блок_даёт_внятную_ошибку(monkeypatch):
    подсунуть(monkeypatch)
    with pytest.raises(StepFailed, match="не найден"):
        ctx_().run("нет_такого")


def test_сломанный_блок_даёт_внятную_ошибку(monkeypatch):
    реестр = подсунуть(monkeypatch, битый=(lambda ctx: None, {}))
    реестр["битый"].error = "SyntaxError: где-то"
    реестр["битый"].module = None
    with pytest.raises(StepFailed, match="не загружается"):
        ctx_().run("битый")


def test_журнал_показывает_вложенность(monkeypatch):
    lines = []
    подсунуть(monkeypatch,
              outer=(lambda ctx: (ctx.log("во внешнем"), ctx.run("inner")), {}),
              inner=(lambda ctx: ctx.log("во внутреннем"), {}))
    ctx_(lines).run("outer")
    текст = "\n".join(lines)
    assert "→ блок «outer»" in текст
    assert "→ блок «inner»" in текст
    # вложенный блок пишется с отступом, иначе в журнале каша
    assert any(l.startswith("  ") and "во внутреннем" in l for l in lines), lines


def test_ошибка_внутри_блока_называет_блок(monkeypatch):
    def падает(ctx):
        ctx.fail("кнопки нет")
    подсунуть(monkeypatch, login=(падает, {}))
    with pytest.raises(StepFailed, match="login"):
        ctx_().run("login")
