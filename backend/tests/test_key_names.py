from farm.control import input as inp


def test_recents_uses_u2_recent_name():
    assert inp._u2_key_name("recents") == "recent"


def test_keys_without_u2_name_go_to_adb(monkeypatch):
    calls = []
    monkeypatch.setattr(inp, "via_u2", lambda s, a: calls.append("u2") or True)
    monkeypatch.setattr(inp.adb, "shell", lambda s, a, **k: calls.append(a))
    inp.key("S", "tab")
    assert calls == [["input", "keyevent", "KEYCODE_TAB"]]


def test_recents_pressed_via_u2(monkeypatch):
    pressed = []

    class D:
        def press(self, k):
            pressed.append(k)

    monkeypatch.setattr(inp, "via_u2", lambda s, a: a(D()) or True)
    inp.key("S", "recents")
    assert pressed == ["recent"]
