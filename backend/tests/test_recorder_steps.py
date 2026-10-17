"""Проверки схемы данных, приходящих из конструктора."""
import pytest

from farm.recorder import steps


def test_нормализация_тапа_приводит_координаты_к_float():
    result = steps.normalize_step({"kind": "tap", "args": {"x": "0.5", "y": 1}})
    assert result == {
        "kind": "tap",
        "args": {"x": 0.5, "y": 1.0},
        "selector": None,
        "param": None,
        "note": "",
        "texts": [],
        "crop": None,
        "point": None,
        "any": None,
        "arms": None,
        "report": None,
        "pos": None,
    }


def test_неизвестный_kind_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "танцевать", "args": {}})


def test_нехватка_обязательного_аргумента_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "tap", "args": {"x": 0.5}})


def test_нечисловая_пауза_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "sleep", "args": {"seconds": "скоро"}})


def test_лишние_ключи_отбрасываются():
    result = steps.normalize_step({
        "kind": "key", "args": {"name": "back", "мусор": 1},
        "id": 7, "shot": "data:image/jpeg;base64,AAA", "alts": [1, 2],
    })
    assert result["args"] == {"name": "back"}
    assert set(result) == {"kind", "args", "selector", "param", "note",
                           "texts", "crop", "point", "any", "arms", "report",
                           "pos"}


def test_шаг_click_требует_селектор_с_вызовом_click():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "click", "args": {}, "selector": None})
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click", "args": {},
            "selector": {"call": "tap", "args": "0.5, 0.5"},
        })


def test_селектор_сохраняет_вызов_и_аргументы():
    result = steps.normalize_step({
        "kind": "click", "args": {},
        "selector": {"call": "click", "args": 'resourceId="a:id/b"',
                     "matches": 1, "fragile": False},
    })
    assert result["selector"] == {"call": "click", "args": 'resourceId="a:id/b"',
                                  "fallbacks": []}


def test_запасные_селекторы_чистятся_от_дублей_и_обрезаются():
    result = steps.normalize_step({
        "kind": "click", "args": {},
        "selector": {"call": "click", "args": 'resourceId="a:id/b"',
                     "fallbacks": ['resourceId="a:id/b"',  # дубль основного
                                   'text="Войти"', 'text="Войти"',  # дубль между собой
                                   'description="Войти"',
                                   'textContains="Вой"',
                                   'className="android.widget.Button"']},
    })
    assert result["selector"]["fallbacks"] == [
        'text="Войти"', 'description="Войти"', 'textContains="Вой"']


def test_кривой_запасной_селектор_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click", "args": {},
            "selector": {"call": "click", "args": 'text="a"', "fallbacks": [42]},
        })
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click", "args": {},
            "selector": {"call": "click", "args": 'text="a"', "fallbacks": ["  "]},
        })


def test_параметр_разрешён_только_для_шагов_со_значением():
    ok = steps.normalize_step({"kind": "type", "args": {"value": "x"}, "param": "login"})
    assert ok["param"] == "login"
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "key", "args": {"name": "back"}, "param": "login"})


def test_шаг_shell_требует_команду_и_параметризуется():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "shell", "args": {}})
    result = steps.normalize_step({
        "kind": "shell", "args": {"cmd": "pm clear com.a"}, "param": "target",
    })
    assert result["args"] == {"cmd": "pm clear com.a"}
    assert result["param"] == "target"


def test_кривое_имя_параметра_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "type", "args": {"value": "x"}, "param": "Логин"})


def test_метка_обрезается_и_теряет_переводы_строк():
    result = steps.normalize_step({
        "kind": "key", "args": {"name": "back"}, "note": "  Кнопка\nназад  ",
    })
    assert result["note"] == "Кнопка назад"


def test_нормализация_meta_требует_название():
    with pytest.raises(steps.StepError):
        steps.normalize_meta({"name": "   "})
    assert steps.normalize_meta({"name": " Логин "}) == {
        "name": "Логин", "description": "", "watch_popups": True, "human": True,
    }


def test_нормализация_params_проверяет_имена():
    with pytest.raises(steps.StepError):
        steps.normalize_params({"Логин": {"label": "Логин", "default": "x"}})
    assert steps.normalize_params({"login": {"default": "x"}}) == {
        "login": {"label": "login", "default": "x"},
    }


def test_шаг_ссылается_на_необъявленный_параметр():
    items = [steps.normalize_step({"kind": "type", "args": {"value": "x"}, "param": "login"})]
    with pytest.raises(steps.StepError):
        steps.check_params({}, items)
    steps.check_params({"login": {"label": "Логин", "default": "x"}}, items)


def test_запасные_слои_click_нормализуются():
    result = steps.normalize_step({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Войти"'},
        "texts": [" Войти ", "Log in", "Войти"],
        "crop": "07_login.png",
        "point": [0.52, 0.81],
    })
    assert result["texts"] == ["Войти", "Log in"]   # обрезка пробелов и дедуп
    assert result["crop"] == "07_login.png"
    assert result["point"] == [0.52, 0.81]


def test_click_без_слоёв_даёт_пустые_значения():
    result = steps.normalize_step({
        "kind": "click",
        "selector": {"call": "click", "args": 'text="Ок"'},
    })
    assert result["texts"] == []
    assert result["crop"] is None
    assert result["point"] is None


def test_кроп_с_выходом_из_папки_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click",
            "selector": {"call": "click", "args": 'text="Ок"'},
            "crop": "../побег.png",
        })


def test_координаты_вне_диапазона_отвергаются():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click",
            "selector": {"call": "click", "args": 'text="Ок"'},
            "point": [1.5, 0.5],
        })


def test_слои_запрещены_другим_шагам():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "sleep", "args": {"seconds": 1},
                              "texts": ["x"]})


def test_шаг_expect_нормализуется():
    result = steps.normalize_step({
        "kind": "expect",
        "args": {"name": "login"},
        "any": ['resourceId="com.app:id/title"', 'text="Вход"'],
    })
    assert result["kind"] == "expect"
    assert result["any"] == ['resourceId="com.app:id/title"', 'text="Вход"']


def test_expect_требует_признаки():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "expect", "args": {"name": "login"},
                              "any": []})


def test_поле_any_запрещено_шагу_click():
    with pytest.raises(steps.StepError):
        steps.normalize_step({
            "kind": "click",
            "selector": {"call": "click", "args": 'text="Ок"'},
            "any": ['text="Вход"'],
        })


def test_позиция_узла_принимается():
    result = steps.normalize_step(
        {"kind": "tap", "args": {"x": 0.1, "y": 0.2}, "pos": [120, 340]})
    assert result["pos"] == [120, 340]


def test_позиция_узла_округляется_до_пикселя():
    result = steps.normalize_step(
        {"kind": "unlock", "args": {}, "pos": [12.6, -3.4]})
    assert result["pos"] == [13, -3]


def test_некорректная_позиция_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "unlock", "args": {}, "pos": [1]})
    with pytest.raises(steps.StepError):
        steps.normalize_step({"kind": "unlock", "args": {}, "pos": ["x", 1]})


def test_позиция_с_бесконечностью_отвергается():
    with pytest.raises(steps.StepError):
        steps.normalize_step(
            {"kind": "unlock", "args": {}, "pos": [float("inf"), 0]})


def test_позиция_доступна_развилке():
    result = steps.normalize_step({
        "kind": "branch", "args": {"name": "x"},
        "arms": [{"name": "a", "any": ['text="1"']}],
        "pos": [5, 6],
    })
    assert result["pos"] == [5, 6]
