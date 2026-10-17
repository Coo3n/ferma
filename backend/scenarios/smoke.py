"""Быстрая проверка живости устройства.

Ничего не запускает и не меняет: будит экран, читает заряд и снимает кадр.
Годится, чтобы проверить ферму после изменений и убедиться, что устройство
отзывается на команды.
"""

NAME = "Проверка связи"
DESCRIPTION = "Разбудить экран, прочитать заряд, снять скриншот"

PARAMS = {
    "shot": {"label": "Делать скриншот", "type": "bool", "default": True},
}


def run(ctx):
    ctx.unlock()
    ctx.log(f"устройство: {ctx.device_name} ({ctx.serial})")
    ctx.log(f"разрешение: {ctx.size}")

    battery = ctx.shell("dumpsys battery | grep level")
    ctx.log(f"батарея: {battery.strip()}")

    ctx.home()
    ctx.sleep(0.5)

    if ctx.params["shot"]:
        ctx.screenshot("home")

    ctx.log("устройство отвечает")
