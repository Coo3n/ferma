"""Структурные селекторы: колонка действий, панель вкладок, плитки, отправка."""
from farm.ui import structure, tree

W, H = 1080, 2280


def el(cls, box, kids="", clickable=False):
    x0, y0, x1, y1 = box
    return (f'<node class="{cls}" bounds="[{x0},{y0}][{x1},{y1}]" '
            f'clickable="{"true" if clickable else "false"}" text="" '
            f'resource-id="" content-desc="" package="p">{kids}</node>')


FL, LL, ET = "android.widget.FrameLayout", "android.widget.LinearLayout", "android.widget.EditText"


def column(plus_clickable=True):
    avatar = el("android.widget.ImageView", (910, 910, 1070, 1000))
    plus = el("android.widget.ImageView", (960, 1010, 1020, 1060), clickable=plus_clickable)
    wrapper = el(FL, (900, 900, 1080, 1100), el(FL, (900, 900, 1080, 1100), avatar + plus))
    rest = "".join(el(FL, (900, 1100 + i * 200, 1080, 1300 + i * 200), clickable=True)
                   for i in range(4))
    return el(LL, (900, 900, 1080, 1900), wrapper + rest)


def screen(*children):
    return f'<hierarchy>{el(FL, (0, 0, W, H), "".join(children))}</hierarchy>'


def parse(*children):
    return tree.parse(screen(*children), W, H)


def test_action_column_found_and_ordered_top_down():
    nodes = parse(column())
    col = structure.action_column(nodes)
    assert len(col) == 5
    tops = [n.bounds[1] for n in col]
    assert tops == sorted(tops)


def test_action_column_ignores_left_side_and_short_lists():
    left = el(LL, (0, 900, 200, 1900), "".join(el(FL, (0, 900 + i * 200, 200, 1100 + i * 200)) for i in range(5)))
    short = el(LL, (900, 900, 1080, 1700), "".join(el(FL, (900, 900 + i * 200, 1080, 1100 + i * 200)) for i in range(4)))
    assert structure.action_column(parse(left, short)) == []


def test_follow_plus_is_second_child_of_inner_and_clickable():
    nodes = parse(column())
    col = structure.action_column(nodes)
    plus = structure.follow_plus(nodes, col)
    assert plus is not None and plus.clickable
    assert structure.follow_plus(parse(column(plus_clickable=False)),
                                 structure.action_column(parse(column(plus_clickable=False)))) is None
    assert structure.follow_plus(nodes, []) is None


def test_tab_bar_five_children_at_bottom_left_to_right():
    tabs = el(LL, (0, 2200, 1080, 2250), "".join(el(FL, (i * 216, 2200, i * 216 + 216, 2250), clickable=True) for i in range(5)))
    nodes = parse(column(), tabs)
    bar = structure.tab_bar(nodes)
    assert len(bar) == 5
    assert [n.bounds[0] for n in bar] == sorted(n.bounds[0] for n in bar)
    # колонка действий (пять детей, но справа и выше) за панель не принимается
    assert all(n.bounds[1] > 0.9 for n in bar)


def test_tab_bar_absent():
    assert structure.tab_bar(parse(column())) == []


def test_grid_tiles_need_two_children_and_nested_second():
    good = el(FL, (0, 400, 500, 900), el(FL, (0, 400, 500, 450)) + el(FL, (0, 450, 500, 900), el(FL, (0, 450, 500, 500))), clickable=True)
    flat = el(FL, (500, 400, 1000, 900), el(FL, (500, 400, 1000, 450)) + el(FL, (500, 450, 1000, 900)), clickable=True)
    single = el(FL, (0, 900, 500, 1400), el(FL, (0, 900, 500, 950)), clickable=True)
    tiles = structure.grid_tiles(parse(good, flat, single))
    assert len(tiles) == 1 and tiles[0].bounds[0] == 0.0


def test_send_after_input_is_last_sibling():
    box = el(LL, (0, 2000, 1080, 2200), el(ET, (50, 2000, 800, 2200)) + el("android.widget.ImageView", (900, 2000, 1050, 2200), clickable=True))
    nodes = parse(box)
    send = structure.send_after_input(nodes)
    assert send is not None and send.bounds[0] > 0.8


def test_send_after_input_when_input_is_last_or_missing():
    only = el(LL, (0, 2000, 1080, 2200), el(ET, (50, 2000, 800, 2200)))
    assert structure.send_after_input(parse(only)) is None
    assert structure.send_after_input(parse(column())) is None


def test_center():
    nodes = parse(el(FL, (100, 200, 300, 600)))
    inner = [n for n in nodes if n.bounds[0] > 0][0]
    cx, cy = structure.center(inner)
    assert abs(cx - 200 / W) < 1e-6 and abs(cy - 400 / H) < 1e-6
