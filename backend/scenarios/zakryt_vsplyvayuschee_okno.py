"""Записано конструктором фермы 17.10.2026."""
RECORDED = True
NAME = "Закрыть всплывающее окно"
DESCRIPTION = "Отвод: записан обучением на месте"


def run(ctx):
    ctx.expect_screen("screen1", any=[dict(description="Close"), dict(text="Delivery time"), dict(text="Up to 11 Days")])
    ctx.click_target(sel=[dict(description="Close")], text=["Close"], img="02_click.png", at=(0.947, 0.802))  # «Close»
