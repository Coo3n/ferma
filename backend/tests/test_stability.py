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


# ---- признак загрузки -------------------------------------------------------

LOADING = '<node class="android.widget.ProgressBar" resource-id="" bounds="[0,0][10,10]"/>'


def test_is_loading_по_классу_и_id():
    assert stability.is_loading(LOADING)
    assert stability.is_loading('<node class="x" resource-id="a:id/shimmer_view"/>')
    assert stability.is_loading('<node class="x" resource-id="a:id/SkeletonRow"/>')
    assert not stability.is_loading('<node class="x" text="Loading" resource-id="a:id/title"/>')
    assert not stability.is_loading("")


def test_загрузка_не_даёт_стабильности_до_таймаута():
    assert stability.wait_stable(
        "x", timeout=0.05, quiet=0, dump=lambda: LOADING, sleep=lambda s: None,
        shot=None,
    ) is False


def test_загрузка_ушла_стабильно():
    dumps = iter([LOADING, LOADING, "<a/>", "<a/>"])
    assert stability.wait_stable(
        "x", timeout=5, quiet=0, dump=lambda: next(dumps), sleep=lambda s: None,
    ) is True


# ---- пиксельный дифф --------------------------------------------------------

def _png(color, size=(40, 40), patch=None):
    import io
    from PIL import Image
    im = Image.new("RGB", size, color)
    if patch:
        im.paste((255, 255, 255), patch)
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


def test_frames_differ_одинаковые_и_разные():
    a = _png((10, 10, 10))
    assert stability.frames_differ(a, _png((10, 10, 10)), 0.01) is False
    assert stability.frames_differ(a, _png((250, 250, 250)), 0.01) is True


def test_frames_differ_мелкая_правка_ниже_порога():
    a = _png((0, 0, 0))
    b = _png((0, 0, 0), patch=(0, 0, 2, 2))   # часы в углу
    assert stability.frames_differ(a, b, 0.05) is False


def test_frames_differ_мусор_не_падает():
    assert stability.frames_differ(b"abc", b"abc", 0.01) is False
    assert stability.frames_differ(b"abc", b"abd", 0.01) is True
    assert stability.frames_differ(None, b"abd", 0.01) is True


def test_вечная_анимация_но_кадры_те_же_считается_стабильной():
    counter = itertools.count()
    assert stability.wait_stable(
        "x", timeout=0.05, quiet=0, dump=lambda: str(next(counter)),
        sleep=lambda s: None, shot=lambda: _png((5, 5, 5)),
    ) is True


def test_вечная_анимация_и_кадры_разные_таймаут():
    counter = itertools.count()
    frames = itertools.cycle([_png((0, 0, 0)), _png((255, 255, 255))])
    assert stability.wait_stable(
        "x", timeout=0.05, quiet=0, dump=lambda: str(next(counter)),
        sleep=lambda s: None, shot=lambda: next(frames),
    ) is False


# ---- рамка цели -------------------------------------------------------------

def _tree(b):
    return ('<hierarchy><node text="Ok" resource-id="a:id/ok" '
            f'bounds="{b}"/></hierarchy>')


def test_find_bounds():
    assert stability.find_bounds(_tree("[1,2][30,40]"), text="Ok") == (1, 2, 30, 40)
    assert stability.find_bounds(_tree("[1,2][30,40]"), resourceId="a:id/ok") == (1, 2, 30, 40)
    assert stability.find_bounds(_tree("[1,2][30,40]"), text="Нет") is None
    assert stability.find_bounds("<<мусор", text="Ok") is None


def test_wait_target_stable_ждёт_пока_рамка_замрёт():
    dumps = iter([_tree("[0,100][10,110]"), _tree("[0,60][10,70]"),
                  _tree("[0,50][10,60]"), _tree("[0,50][10,60]")])
    r = stability.wait_target_stable(
        "x", lambda xml: stability.find_bounds(xml, text="Ok"),
        timeout=5, quiet=0, dump=lambda: next(dumps), sleep=lambda s: None)
    assert r == (0, 50, 10, 60)


def test_wait_target_stable_таймаут_отдаёт_последнюю_рамку():
    n = itertools.count()
    r = stability.wait_target_stable(
        "x", lambda xml: stability.find_bounds(xml, text="Ok"),
        timeout=0.05, quiet=0, dump=lambda: _tree(f"[0,{next(n)}][10,500]"),
        sleep=lambda s: None)
    assert r is not None and r[2:] == (10, 500)


def test_wait_target_stable_нет_цели_не_ждёт_таймаут():
    calls = []
    r = stability.wait_target_stable(
        "x", lambda xml: None, timeout=30, quiet=0,
        dump=lambda: calls.append(1) or "<a/>", sleep=lambda s: None)
    assert r is None and len(calls) <= 3


def test_wait_target_stable_дамп_упал():
    def boom():
        raise RuntimeError("x")
    assert stability.wait_target_stable(
        "x", lambda xml: (1, 1, 2, 2), timeout=1, quiet=0, dump=boom,
        sleep=lambda s: None) is None
