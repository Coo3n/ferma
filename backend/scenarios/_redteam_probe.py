"""Пробный сценарий для farm.redteam.harness.

Не появляется в списке сценариев фермы — имя начинается с «_», как и
`_template.py`. Запускается только харнессом напрямую по пути к файлу, не
через обычную очередь задач.

Специально общий: трогает только системные «Настройки», у которых один и
тот же набор пунктов на любом Android, — сравнивать bot/human-профили можно
на любом устройстве без привязки к конкретному стороннему приложению.

Жесты идут через ctx.tap/ctx.swipe/ctx.key напрямую (не ctx.back()/ctx.home()),
чтобы RecordingContext из harness.py успевал их перехватить и записать.
"""
NAME = "_redteam_probe"
DESCRIPTION = "Служебный сценарий для farm.redteam.harness — не запускайте вручную"


def run(ctx):
    ctx.unlock()
    ctx.launch_app("com.android.settings", stop_first=True)
    ctx.scroll_down(1)
    ctx.tap(0.5, 0.28)
    ctx.sleep(0.4)
    ctx.key("back")
    ctx.scroll_down(1)
    ctx.tap(0.5, 0.55)
    ctx.sleep(0.4)
    ctx.key("back")
    ctx.scroll_up(1)
    ctx.key("home")
