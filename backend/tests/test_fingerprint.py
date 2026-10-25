"""Отпечаток экрана и счёт похожести: чистая логика, без телефона."""
from farm import fingerprint as fp, obstacle
from farm.ui import tree


def _xml(*узлы, extra=""):
    return ("<hierarchy>" + "".join(узлы) + extra + "</hierarchy>")


def _n(rid, text="", pkg="com.app", enabled="true", y=0):
    return (f'<node text="{text}" resource-id="{rid}" class="android.widget.Button" '
            f'package="{pkg}" clickable="true" enabled="{enabled}" '
            f'bounds="[0,{y}][100,{y + 50}]"/>')


def _fp(xml, pkg="com.app"):
    return fp.from_xml(xml, 1000, 2000, pkg)


def test_одинаковые_экраны_дают_единицу():
    x = _xml(_n("com.app:id/a", "Да"), _n("com.app:id/b", "Нет", y=100))
    assert fp.similarity(_fp(x), _fp(x)) == 1.0


def test_рамки_не_влияют():
    a = _xml(_n("com.app:id/a", "Да", y=0))
    b = _xml(_n("com.app:id/a", "Да", y=500))
    assert fp.similarity(_fp(a), _fp(b)) == 1.0


def test_состояние_элемента_меняет_ключ():
    a = _xml(_n("com.app:id/a", "Да"))
    b = _xml(_n("com.app:id/a", "Да", enabled="false"))
    assert fp.similarity(_fp(a), _fp(b)) < 1.0


def test_жаккар_и_пакет():
    a = _fp(_xml(_n("com.app:id/a"), _n("com.app:id/b", y=100)))
    b = _fp(_xml(_n("com.app:id/a"), _n("com.app:id/c", y=100)))
    # общих 1 из 3 → 1/3 * 0.85 + 0.15
    assert abs(fp.similarity(a, b) - (0.85 / 3 + 0.15)) < 1e-9
    b["package"] = "com.other"
    assert abs(fp.similarity(a, b) - 0.85 / 3) < 1e-9


def test_пустые_множества_совпадают():
    e = {"package": "p", "keys": []}
    assert fp.similarity(e, e) == 1.0


def test_шторка_не_входит_в_отпечаток():
    a = _xml(_n("com.app:id/a"))
    b = _xml(_n("com.app:id/a"), _n("com.android.systemui:id/clock", "14:22",
                                     pkg="com.android.systemui", y=300))
    assert _fp(a) == _fp(b)


def test_node_key_без_рамок():
    nodes = tree.parse(_xml(_n("com.app:id/a", "Да")), 1000, 2000)
    assert len(fp.node_key(nodes[0])) == 7


def test_слепок_преграды_несёт_отпечаток_и_старые_без_него_живут():
    x = _xml(_n("com.app:id/a", "Закрыть"))
    сл = obstacle.capture(x, 1000, 2000, package="com.app")
    assert сл["fingerprint"]["keys"]


def test_преграды_с_похожим_отпечатком_сливаются():
    базовые = [_n(f"com.app:id/k{i}", f"Текст {i}", y=i * 60) for i in range(20)]
    a = obstacle.capture(_xml(*базовые), 1000, 2000, package="com.app")
    # другой первый кандидат, но экран почти тот же (1 узел из 21 другой)
    b = obstacle.capture(_xml(_n("com.app:id/new", "Новое", y=1500), *базовые),
                         1000, 2000, package="com.app")
    assert obstacle._key(a) != obstacle._key(b)
    out = obstacle.uncovered([a, b], [])
    assert len(out) == 1 and out[0]["hits"] == 2
    assert "fingerprint" not in out[0]


def test_разные_экраны_не_сливаются():
    a = obstacle.capture(_xml(_n("com.app:id/a", "А")), 1000, 2000, package="com.app")
    b = obstacle.capture(_xml(_n("com.app:id/z", "Я")), 1000, 2000, package="com.app")
    assert len(obstacle.uncovered([a, b], [])) == 2
