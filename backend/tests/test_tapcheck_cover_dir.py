"""Проверка эффекта тапа, тап мимо перекрывашки, направленный near."""
from farm import config, deviations as dv, resolve
from farm.context import DeviceContext
from farm.ui import scope, tree


def _xml(*nodes):
    body = "".join(
        f'<node text="{t}" clickable="{c}" checkable="{k}" bounds="[{b[0]},{b[1]}][{b[2]},{b[3]}]"/>'
        for t, c, k, b in nodes)
    return f'<hierarchy><node bounds="[0,0][1000,1000]">{body}</node></hierarchy>'


# ---------- перекрывашка
def test_свободный_центр_остаётся_центром():
    n = tree.parse(_xml(("a", "true", "false", (0, 0, 400, 100))), 1000, 1000)
    assert tree.tap_point(n[1], tree.coverers(n, n[1])) == (0.2, 0.05)


def test_перекрытый_центр_смещается_в_свободный_кусок():
    n = tree.parse(_xml(("a", "true", "false", (0, 0, 400, 100)),
                        ("fab", "true", "false", (100, 0, 400, 100))), 1000, 1000)
    x, y = tree.tap_point(n[1], tree.coverers(n, n[1]))
    assert x < 0.1 and 0 < y < 0.1


def test_сосед_раньше_в_дампе_не_перекрывает():
    n = tree.parse(_xml(("under", "true", "false", (0, 0, 400, 100)),
                        ("a", "true", "false", (0, 0, 400, 100))), 1000, 1000)
    assert tree.coverers(n, n[2]) == []


def test_полностью_закрытый_даёт_None():
    n = tree.parse(_xml(("a", "true", "false", (0, 0, 400, 100)),
                        ("cover", "true", "false", (0, 0, 500, 200))), 1000, 1000)
    assert tree.tap_point(n[1], tree.coverers(n, n[1])) is None
    assert resolve.free_point(n, n[1]) == (0.2, 0.05)


# ---------- направление
def _ряд():
    return tree.parse(_xml(("Like", "true", "false", (50, 100, 150, 160)),
                           ("nick", "false", "false", (400, 100, 600, 160)),
                           ("Like", "true", "false", (800, 100, 900, 160))), 1000, 1000)


def test_справа_и_слева_от_ника():
    n = _ряд()
    r, _ = scope.pick(n, {"text": "Like"}, near={"text": "nick", "dir": "right"})
    l, _ = scope.pick(n, {"text": "Like"}, near={"text": "nick", "dir": "left"})
    assert r.id == 3 and l.id == 1


def test_без_dir_прежнее_поведение_и_пустая_сторона():
    n = _ряд()
    assert scope.pick(n, {"text": "Like"}, near={"text": "nick"})[0] is not None
    assert scope.pick(n, {"text": "Like"}, near={"text": "nick", "dir": "below"}) == (None, "target")


# ---------- эффект тапа
def _ctx(monkeypatch, dumps, checkable=False):
    ctx = DeviceContext("s", logger=lambda m: None)
    monkeypatch.setattr(ctx, "_settle", lambda *a, **k: None)
    monkeypatch.setattr(ctx, "sleep", lambda s: None)
    taps = []
    monkeypatch.setattr(ctx, "tap", lambda x, y: taps.append((x, y)))
    it = iter(dumps)
    last = [dumps[-1]]
    monkeypatch.setattr(ctx, "dump_hierarchy", lambda: next(it, last[0]))
    monkeypatch.setattr(ctx, "screen_bytes", lambda: b"")
    monkeypatch.setattr(resolve, "resolve",
                        lambda c, **kw: resolve.Hit(0.5, 0.5, "selector", "", checkable=checkable))
    monkeypatch.setattr(config, "TAPCHECK", True)
    dv.deviations.clear()
    return ctx, taps


def test_эффект_есть_повтора_нет(monkeypatch):
    ctx, taps = _ctx(monkeypatch, ["a", "b"])
    ctx.click_target(sel=[{"text": "X"}])
    assert len(taps) == 1 and dv.deviations.list() == []


def test_без_эффекта_повтор_и_отклонение(monkeypatch):
    ctx, taps = _ctx(monkeypatch, ["a"])
    ctx.click_target(sel=[{"text": "X"}])
    assert len(taps) == 2
    assert [d["kind"] for d in dv.deviations.list()] == ["noeffect"]


def test_повтор_помог_отклонения_нет(monkeypatch):
    ctx, taps = _ctx(monkeypatch, ["a", "a", "a", "b"])
    ctx.click_target(sel=[{"text": "X"}])
    assert len(taps) == 2 and dv.deviations.list() == []


def test_переключатель_без_повтора(monkeypatch):
    ctx, taps = _ctx(monkeypatch, ["a"], checkable=True)
    ctx.click_target(sel=[{"text": "X"}])
    assert len(taps) == 1
    assert [d["kind"] for d in dv.deviations.list()] == ["noeffect"]


def test_выключатель(monkeypatch):
    ctx, taps = _ctx(monkeypatch, ["a"])
    monkeypatch.setattr(config, "TAPCHECK", False)
    ctx.click_target(sel=[{"text": "X"}])
    assert len(taps) == 1 and dv.deviations.list() == []
