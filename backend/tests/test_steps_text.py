from farm.steps_text import describe


def texts(steps):
    return [(r["text"], r["depth"]) for r in describe(steps)]


def one(kind, args=None, **extra):
    step = {"kind": kind, "args": args or {}}
    step.update(extra)
    return describe([step])[0]["text"]


def test_empty():
    assert describe([]) == []


def test_launch_and_apps():
    assert one("launch_app", {"package": "com.x"}) == "Открыть приложение"
    assert one("ensure_app", {"package": "com.x"}) == "Проверить, что приложение установлено"
    assert one("stop_app", {"package": "com.x"}) == "Закрыть приложение"
    assert one("open_url", {"url": "https://a.b"}) == "Открыть ссылку"


def test_sleep():
    assert one("sleep", {"seconds": 3}) == "Пауза 3 с"
    assert one("sleep", {"seconds": 6, "seconds_max": 14}) == "Пауза 6–14 с"
    assert one("sleep", {"seconds": 2.5}) == "Пауза 2.5 с"


def test_swipe_directions():
    assert one("swipe", {"x1": 500, "y1": 1500, "x2": 500, "y2": 500}) == "Провести вверх"
    assert one("swipe", {"x1": 500, "y1": 500, "x2": 500, "y2": 1500}) == "Провести вниз"
    assert one("swipe", {"x1": 900, "y1": 500, "x2": 100, "y2": 500}) == "Провести влево"
    assert one("swipe", {"x1": 100, "y1": 500, "x2": 900, "y2": 500}) == "Провести вправо"


def test_click_variants():
    sel = lambda a: {"call": "click", "args": a}
    assert one("click", selector=sel('description="Нравится"')) == "Нажать «Нравится»"
    assert one("click", selector=sel('text="Войти"')) == "Нажать «Войти»"
    assert one("click", selector=sel('resourceId="app:id/like"')) == "Нажать на элемент"
    assert one("click", selector=sel('resourceId="app:id/like"'), note="Лайк") == "Лайк"
    assert one("click") == "Нажать на элемент"


def test_tap_and_taps():
    assert one("tap", {"x": 1, "y": 2}) == "Нажать в точку экрана"
    assert one("double_tap", {"x": 1, "y": 2}) == "Двойное нажатие"
    assert one("long_tap", {"x": 1, "y": 2}) == "Долгое нажатие"


def test_type_and_key():
    assert one("type", {"value": "привет"}) == "Ввести текст"
    assert one("type", {"value": "", "account": "login"}) == "Ввести логин из аккаунта телефона"
    assert one("type", {"value": "", "account": "password"}) == "Ввести пароль из аккаунта телефона"
    assert one("key", {"name": "BACK"}) == "Нажать «Назад»"
    assert one("key", {"name": "HOME"}) == "Нажать «Домой»"
    assert one("key", {"name": "ENTER"}) == "Нажать «Ввод»"
    assert one("key", {"name": "WEIRD_KEY"}) == "Нажать клавишу"


def test_budget():
    assert one("budget", {"name": "лайки", "limit": 200}) == "Потолок за сутки: лайки — 200"


def test_wait_family():
    assert one("wait", {"timeout": 20}, any=['text="Новости"']) == "Ждать, пока появится «Новости»"
    assert one("wait") == "Ждать, пока появится нужное"
    assert one("wait_gone", any=['text="Загрузка"']) == "Ждать, пока исчезнет «Загрузка»"


def test_misc_kinds():
    assert one("unlock") == "Разблокировать телефон"
    assert one("shell", {"cmd": "rm -rf /x"}) == "Выполнить команду"
    assert one("screenshot") == "Сделать скриншот"
    assert one("break") == "Выйти из повтора"
    assert one("finish", {"result": "ok"}) == "Закончить сценарий"
    assert one("finish", {"result": "fail"}) == "Закончить сценарий с ошибкой"
    assert one("call", {"scenario": "x"}) == "Запустить другой сценарий"
    assert one("proxy", {"account": "vk"}) == "Включить прокси аккаунта"
    assert one("proxy", {"off": True}) == "Выключить прокси"
    assert one("expect", {"name": "лента"}) == "Убедиться, что открыт экран «лента»"
    assert one("branch", {"name": "лента"}) == "Развилка «лента»"


def test_blocks_headers():
    assert one("loop", {"span": 1, "times": 30}) == "Повторять 30 раз"
    assert one("loop", {"span": 1, "minutes": 10}) == "Повторять 10 минут"
    assert one("loop", {"span": 1}) == "Повторять"
    assert one("chance", {"span": 1, "percent": 20}) == "С шансом 20%:"
    assert one("until", {"span": 1, "tries": 5}, any=['text="Подписаться"']) == \
        "Повторять, пока не появится «Подписаться»"
    assert one("if_seen", {"span": 1}, any=['text="Ещё"']) == "Если на экране есть «Ещё»:"
    assert one("if_seen", {"span": 1, "negate": True}, any=['text="Ещё"']) == \
        "Если на экране нет «Ещё»:"
    assert one("if_phone", {"span": 1, "check": "battery_below", "percent": 20}) == \
        "Если заряд телефона ниже 20%:"
    assert one("if_phone", {"span": 1, "check": "offline", "negate": True}) == \
        "Если на телефоне есть интернет:"


def test_nesting_depth():
    steps = [
        {"kind": "launch_app", "args": {"package": "p"}},
        {"kind": "loop", "args": {"span": 3, "times": 3}},
        {"kind": "chance", "args": {"span": 1, "percent": 20}},
        {"kind": "click", "selector": {"call": "click", "args": 'description="Нравится"'}},
        {"kind": "sleep", "args": {"seconds": 1}},
        {"kind": "finish", "args": {}},
    ]
    assert texts(steps) == [
        ("Открыть приложение", 0),
        ("Повторять 3 раза", 0),
        ("С шансом 20%:", 1),
        ("Нажать «Нравится»", 2),
        ("Пауза 1 с", 1),
        ("Закончить сценарий", 0),
    ]


def test_unknown_kind():
    assert one("teleport") == "Шаг: teleport"
    assert describe([{"kind": "teleport"}])[0]["depth"] == 0


def test_span_beyond_end_is_clamped():
    steps = [
        {"kind": "loop", "args": {"span": 99, "times": 2}},
        {"kind": "chance", "args": {"span": 50, "percent": 10}},
        {"kind": "break", "args": {}},
    ]
    assert [r["depth"] for r in describe(steps)] == [0, 1, 2]


def test_bad_input_does_not_crash():
    assert describe([{"kind": "loop", "args": {"span": "x"}}, {"kind": "break"}])[1]["depth"] == 0
    assert describe([{}, {"kind": None}])[0]["text"].startswith("Шаг")


def test_no_ids_or_coordinates_leak():
    text = one("click", selector={"call": "click", "args": 'resourceId="app:id/like"'})
    assert "app:id" not in text
    assert "500" not in one("swipe", {"x1": 500, "y1": 1500, "x2": 500, "y2": 500})
