"""Необязательный шаг: промах не держит задачу и пишет отклонение."""
import json

import pytest

from farm import deviations as dv
from farm.context import DeviceContext, HOLD_RETRY, StepFailed


class Ctx(DeviceContext):
    def __init__(self, **kw):
        super().__init__("s", logger=lambda m: None, **kw)

    def _settle(self, *a, **k):
        pass

    def _rescue(self):
        return False

    def find(self, timeout=10, **selector):
        return None

    def screenshot(self, name=""):
        return "/x/skipped.png"


def test_optional_не_спрашивает_человека_и_пишет_отклонение():
    dv.deviations.clear()
    спрошено = []
    ctx = Ctx(hold=lambda что: спрошено.append(что) or HOLD_RETRY)
    assert ctx.optional(lambda: ctx.click(timeout=0, text="Позже"), what="шаг 3") is None
    assert спрошено == []
    items = dv.deviations.list()
    assert [i["kind"] for i in items] == ["skipped_optional"]


def test_обязательный_шаг_по_прежнему_спрашивает():
    спрошено = []
    ctx = Ctx(hold=lambda что: спрошено.append(что) or "drop")
    with pytest.raises(StepFailed):
        ctx.attempt(lambda: ctx.click(timeout=0, text="Позже"))
    assert спрошено


def test_счёт_похожести_в_сообщении(tmp_path):
    from farm import fingerprint as fp
    xml = ('<hierarchy><node text="Вход" resource-id="com.a:id/x" class="B" '
           'package="com.a" clickable="true" bounds="[0,0][100,50]"/></hierarchy>')
    эталон = fp.from_xml(xml, 1000, 2000, "com.a")
    (tmp_path / "meta.json").write_text(json.dumps({"screens": {"login": эталон}}))

    class C(Ctx):
        size = (1000, 2000)
        def dump_hierarchy(self): return xml
        def current_app(self): return "com.a"
    ctx = C(scenario_assets=tmp_path)
    assert "на 100%" in ctx._likeness(["login"])
    assert Ctx()._likeness(["login"]) == ""
