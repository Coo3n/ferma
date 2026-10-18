"""Слепок преграды: что помешало сценарию и как это опознать.

Снимается в момент падения, потому что к моменту, когда человек дойдёт до
журнала, устройство уже заберёт следующая задача и экран сменится.
Устройство не нужно: на входе XML-дамп, на выходе словарь.
"""
import pytest

from farm import obstacle

ДАМП = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node text="Выберите тариф" resource-id="com.app:id/tariff_title"
        class="android.widget.TextView" content-desc="" bounds="[0,200][1080,300]"/>
  <node text="Год за 2990 ₽" resource-id="com.app:id/year"
        class="android.widget.Button" content-desc="" bounds="[40,400][1040,520]"/>
  <node text="Позже" resource-id="com.app:id/later"
        class="android.widget.Button" content-desc="" bounds="[40,600][1040,700]"/>
</hierarchy>"""


def test_слепок_называет_пакет_и_тексты():
    сл = obstacle.capture(ДАМП, 1080, 1920, package="com.app")
    assert сл["package"] == "com.app"
    assert "Выберите тариф" in сл["texts"]


def test_кандидаты_условия_непустые_и_разные():
    сл = obstacle.capture(ДАМП, 1080, 1920, package="com.app")
    кандидаты = сл["candidates"]
    assert 1 <= len(кандидаты) <= obstacle.MAX_CANDIDATES
    ключи = [tuple(sorted(c["selector"].items())) for c in кандидаты]
    assert len(set(ключи)) == len(ключи), "кандидаты повторяются"


def test_каждый_кандидат_годен_для_стража():
    """Кандидат кладётся прямо в guard.when — значит, обязан быть валидным."""
    from farm import guards
    сл = obstacle.capture(ДАМП, 1080, 1920, package="com.app")
    for c in сл["candidates"]:
        guards._parse_guard({
            "name": "проверка",
            "when": {"any": [c["selector"]]},
            "action": {"key": "back"},
        }, "тест")


def test_кандидаты_описаны_по_человечески():
    сл = obstacle.capture(ДАМП, 1080, 1920, package="com.app")
    # человек выбирает условие глазами: подпись обязана что-то значить
    assert all(c["label"].strip() for c in сл["candidates"])


def test_resourceId_предпочтительнее_текста():
    """resourceId не зависит от локали — он должен идти первым."""
    сл = obstacle.capture(ДАМП, 1080, 1920, package="com.app")
    assert "resourceId" in сл["candidates"][0]["selector"]


def test_битый_дамп_не_роняет():
    сл = obstacle.capture("не xml вовсе", 1080, 1920, package="com.app")
    assert сл["candidates"] == []
    assert сл["package"] == "com.app"


def test_экран_без_опознавательных_знаков():
    пустой = '<?xml version="1.0"?><hierarchy><node bounds="[0,0][10,10]"/></hierarchy>'
    сл = obstacle.capture(пустой, 1080, 1920, package="com.app")
    assert сл["candidates"] == []


# ------------------------------------------------- непокрытые преграды

ПРЕГРАДА = {"package": "com.app", "texts": ["Выберите тариф"],
            "candidates": [{"selector": {"resourceId": "com.app:id/tariff"},
                            "label": "по идентификатору: tariff"}]}


def правило(sel, name="есть"):
    return {"name": name, "when": {"any": [sel]}, "action": {"run": "x"}}


def test_преграда_без_правила_считается_непокрытой():
    непокрытые = obstacle.uncovered([ПРЕГРАДА], rules=[])
    assert len(непокрытые) == 1
    assert непокрытые[0]["texts"] == ["Выберите тариф"]


def test_преграда_с_правилом_не_показывается():
    rules = [правило({"resourceId": "com.app:id/tariff"})]
    assert obstacle.uncovered([ПРЕГРАДА], rules) == []


def test_правило_на_другой_признак_не_закрывает():
    rules = [правило({"resourceId": "com.app:id/другое"})]
    assert len(obstacle.uncovered([ПРЕГРАДА], rules)) == 1


def test_одинаковые_преграды_схлопываются_со_счётчиком():
    непокрытые = obstacle.uncovered([ПРЕГРАДА, ПРЕГРАДА, ПРЕГРАДА], rules=[])
    assert len(непокрытые) == 1
    assert непокрытые[0]["hits"] == 3, "частота показывает, что чинить первым"


def test_частые_преграды_идут_первыми():
    редкая = dict(ПРЕГРАДА, texts=["Реклама"],
                  candidates=[{"selector": {"resourceId": "com.app:id/ad"},
                               "label": "по идентификатору: ad"}])
    непокрытые = obstacle.uncovered([ПРЕГРАДА, ПРЕГРАДА, редкая], rules=[])
    assert непокрытые[0]["hits"] == 2


# ------------------------------- системная шторка не должна попадать в условие

СИСТЕМНЫЙ = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node text="14:22" resource-id="com.android.systemui:id/clock"
        content-desc="" class="android.widget.TextView" bounds="[0,0][200,80]"/>
  <node text="" resource-id="com.android.systemui:id/status_bar"
        content-desc="" class="android.view.View" bounds="[0,0][1080,80]"/>
  <node text="Что-то пошло не так" resource-id="com.example.app.dev:id/errorTitle"
        content-desc="" class="android.widget.TextView" bounds="[100,900][980,980]"/>
</hierarchy>"""


def test_системные_узлы_не_идут_в_условие():
    """Найдено на живом приложении: все пять кандидатов оказались из systemui.

    Страж по com.android.systemui:id/status_bar срабатывал бы на каждом
    экране любого приложения — условие, которое всегда истинно, бесполезно.
    """
    сл = obstacle.capture(СИСТЕМНЫЙ, 1080, 2340, package="com.example.app.dev")
    все = str(сл["candidates"])
    assert "systemui" not in все, f"системный узел попал в условие: {все}"
    assert "errorTitle" in все, "узел приложения обязан остаться"


def test_часы_не_попадают_в_тексты():
    """«14:22» меняется каждую минуту — как признак экрана бесполезно."""
    сл = obstacle.capture(СИСТЕМНЫЙ, 1080, 2340, package="com.example.app.dev")
    assert "14:22" not in сл["texts"]
    assert "Что-то пошло не так" in сл["texts"]


def test_без_пакета_фильтр_не_ломается():
    сл = obstacle.capture(СИСТЕМНЫЙ, 1080, 2340, package="")
    assert сл["candidates"], "без пакета отфильтровать нечем — берём что есть"


КАРКАС = """<?xml version='1.0'?>
<hierarchy rotation="0">
  <node text="" resource-id="com.app:id/mainContentRoot" content-desc=""
        class="android.view.View" bounds="[0,0][1080,2340]"/>
  <node text="" resource-id="com.app:id/fragmentTabContainer" content-desc=""
        class="android.view.View" bounds="[0,0][1080,2340]"/>
  <node text="Что-то пошло не так" resource-id="" content-desc=""
        class="android.widget.TextView" bounds="[100,900][980,980]"/>
</hierarchy>"""


def test_каркас_приложения_не_годится_в_условие():
    """Найдено на живом приложении: action_bar_root, mainContentRoot и ещё трое — все
    ровно 100% экрана и присутствуют и на экране ошибки, и на рабочем
    каталоге. Условие по ним истинно всегда, преграду оно не опознаёт.
    """
    сл = obstacle.capture(КАРКАС, 1080, 2340, package="com.app")
    первый = сл["candidates"][0]["selector"]
    assert "textContains" in первый, f"наверху каркас вместо признака: {первый}"
    assert "пошло не так" in str(первый)


def test_каркас_остаётся_запасным_а_не_исчезает():
    сл = obstacle.capture(КАРКАС, 1080, 2340, package="com.app")
    все = str(сл["candidates"])
    assert "mainContentRoot" in все, "выбрасывать не надо — вдруг больше нечего"
