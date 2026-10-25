from farm import obstacle
from farm.ui import selectors as sel


def test_obfuscated_ids_detected():
    for rid in ("com.app:id/a", "com.app:id/b2", "com.app:id/abc", "com.app:id/a1b", "com.app:id/12"):
        assert sel.is_obfuscated_id(rid), rid


def test_plain_ids_kept():
    for rid in ("com.app:id/login_button", "com.app:id/ok", "com.app:id/title",
                "com.app:id/add", "com.app:id/toolbar", ""):
        assert not sel.is_obfuscated_id(rid), rid


def test_obfuscated_class():
    assert sel.is_obfuscated_class("a.b.c")
    assert not sel.is_obfuscated_class("android.widget.Button")
    assert not sel.is_obfuscated_class("com.shop.ui.Banner")


XML = ('<hierarchy><node bounds="[0,0][1000,2000]" package="com.app" text="" resource-id="">'
       '<node bounds="[100,100][900,300]" package="com.app" resource-id="com.app:id/a" text="Обновить"/>'
       '<node bounds="[100,400][900,600]" package="com.app" resource-id="com.app:id/promo_close" text="12:45"/>'
       '</node></hierarchy>')


def test_capture_prefers_stable_over_obfuscated_and_skips_dynamic_text():
    cands = [c["selector"] for c in obstacle.capture(XML, 1000, 2000, "com.app")["candidates"]]
    assert cands[0] == {"resourceId": "com.app:id/promo_close"}
    assert cands.index({"textContains": "Обновить"}) < cands.index({"resourceId": "com.app:id/a"})
    assert {"textContains": "12:45"} not in cands


def test_uncovered_when_rule_uses_non_first_candidate():
    o = {"candidates": [{"selector": {"resourceId": "x:id/long_name"}},
                        {"selector": {"textContains": "Закрыть"}}]}
    rules = [{"when": {"any": [{"textContains": "Закрыть"}]}}]
    assert obstacle.uncovered([o], rules) == []
