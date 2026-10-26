"""Telegram: читает каналы из списка — открывает, листает посты, выходит.

Ничего не публикует. Поиск канала по названию через значок лупы; названия и
подписи значков зависят от языка телефона. Не проверено.
"""
from farm import story

NAME = "Telegram: чтение каналов (по списку)"
DESCRIPTION = "Открывает каналы по списку названий, листает посты вверх и возвращается. Ничего не пишет."
PACKAGE = "org.telegram.messenger"
STEPS = [
    "Открыть Telegram",
    "Взять первый канал из вашего списка",
    "Открыть поиск и ввести название канала",
    "Открыть найденный канал",
    "Пролистать посты к старым, с паузой на каждом экране",
    "Три раза нажать «Назад» и выйти из канала",
    "Перейти к следующему каналу; после последнего начать новый круг",
]
GALLERY = {"platform": "Telegram", "verified": False, "package": PACKAGE}
PARAMS = {
    "channels": {"label": "Каналы (по строке)", "type": "textarea", "default": "",
                 "help": "Название или @имя канала"},
    "scrolls": {"label": "Сколько раз пролистать каждый", "type": "number", "default": 8, "min": 1, "max": 100},
    "rounds": {"label": "Сколько кругов по списку", "type": "number", "default": 1, "min": 1, "max": 20},
}


def run(ctx):
    channels = story.parse_lines(ctx.params["channels"], 100)
    if not channels:
        ctx.fail("список каналов пуст")
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("Telegram не открылся")
    scrolls = int(ctx.params["scrolls"])
    for _ in ctx.loop(times=int(ctx.params["rounds"]), watch=True):
        for name in channels:
            ctx.log(f"канал: {name}")
            ctx.click_target(sel=[dict(descriptionMatches="(?i)(search|поиск)")], at=(0.88, 0.07))
            ctx.sleep(1)
            ctx.type(name, clear=True)
            ctx.sleep(2)
            ctx.click_target(text=[name], timeout=8)
            ctx.sleep(2)
            for _ in range(scrolls):
                ctx.swipe(0.5, 0.35, 0.5, 0.75, 0.4)    # вниз по экрану = к старым постам
                ctx.pause(1.5, 4)
            for _ in range(3):
                ctx.back()
                ctx.sleep(0.6)
