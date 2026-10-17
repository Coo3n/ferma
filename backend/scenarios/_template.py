"""ШАБЛОН СЦЕНАРИЯ — скопируйте файл под своим именем без подчёркивания в начале.

Файлы, начинающиеся с «_», ферма не показывает в списке.

Что доступно в ctx
------------------
Ввод:
    ctx.tap(x, y)                   координаты 0..1 (доля экрана) или пиксели
    ctx.long_tap(x, y, duration)
    ctx.swipe(x1, y1, x2, y2, duration)
    ctx.scroll_down(n) / ctx.scroll_up(n)
    ctx.type("текст", clear=False)  умеет кириллицу через uiautomator2
    ctx.key("back" | "home" | "enter" | "recents" | "power" | ...)
    ctx.back() / ctx.home() / ctx.unlock(pin=None)

Поиск элементов (селекторы uiautomator2):
    ctx.find(text="Готово", timeout=10)          → элемент или None
    ctx.click(resourceId="com.app:id/ok")        → нажать, упасть если нет
    ctx.click_if_exists(textContains="Разреш")   → True/False
    ctx.exists(description="Меню")
    ctx.wait_gone(text="Загрузка")
    ctx.set_text("value", resourceId="com.app:id/input")
    ctx.d                                        → сырой клиент uiautomator2

Приложения:
    ctx.launch_app("com.example", stop_first=True)
    ctx.wait_app("com.example", timeout=20)
    ctx.current_app() / ctx.stop_app(pkg) / ctx.open_url(url)
    ctx.install("/path/app.apk") / ctx.uninstall(pkg) / ctx.grant(pkg, "CAMERA")
    ctx.packages()

Служебное:
    ctx.log("сообщение")            попадёт в журнал задачи
    ctx.sleep(2)                    пауза с поддержкой отмены
    ctx.fail("почему упало")        остановить сценарий с артефактами
    ctx.screenshot("имя")           сохранить кадр в артефакты
    ctx.save_hierarchy() / ctx.save_logcat()
    ctx.shell("dumpsys battery")
    ctx.watch_popups("Разрешить")   фоновое закрытие диалогов
    ctx.retry(fn, attempts=3)       повтор нестабильного шага
    ctx.params["имя"]               параметры из формы
    ctx.serial, ctx.device_name, ctx.size

Устойчивость (подробнее — в README, раздел «Устойчивость»):
    # Многослойная цель: селекторы → текст → OCR → шаблон → координаты.
    # ctx.click_target(sel=[dict(resourceId="com.app:id/login")],
    #                  text=["Войти", "Log in"], at=(0.5, 0.8))

    # Якорь экрана: падение с «ожидал X, вижу Y» вместо тапов в пустоту.
    # ctx.expect_screen("login", any=[dict(text="Вход")])

    # Развилка: «где я?» вместо «я обязан быть тут». Не падает никогда:
    # один и тот же шаг встречает то онбординг, то пейволл, то каталог.
    # ветка = ctx.which_screen({
    #     "онбординг": [dict(resourceId="com.app:id/skip")],
    #     "каталог": [dict(text="Каталог")],
    # })
    # if ветка == "онбординг":
    #     ctx.run("skip_onboarding")   # блок — обычный сценарий из папки

    # Стражи закрывают известные попапы сами — см. guards/global.json.
"""

NAME = "Шаблон"
DESCRIPTION = "Скопируйте этот файл и напишите свой сценарий"

PARAMS = {
    "package": {"label": "Пакет", "default": "com.android.settings"},
    "count": {"label": "Повторов внутри", "type": "number", "default": 1},
}


def run(ctx):
    ctx.watch_popups()
    ctx.unlock()

    ctx.launch_app(ctx.params["package"])
    if not ctx.wait_app(ctx.params["package"], timeout=15):
        ctx.fail("приложение не открылось")

    for i in range(int(ctx.params["count"])):
        ctx.log(f"итерация {i + 1}")
        ctx.scroll_down()
        ctx.sleep(0.5)

    ctx.screenshot("final")
