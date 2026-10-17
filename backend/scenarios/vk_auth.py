"""Записано конструктором фермы 29.09.2026."""
RECORDED = True
NAME = "vk_auth"


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.shell("pm clear com.vkontakte.android")
    ctx.launch_app("com.vkontakte.android")
    ctx.expect_screen("screen1", any=[dict(description="Уведомление Система Android:"), dict(description="Уведомление RuStore: Самокат"), dict(description="Уведомление Обновление: Доступно обновление")])
    ctx.click_target(sel=[dict(description="Закрыть")], img="04_click.png", at=(0.902, 0.67))  # View
    ctx.expect_screen("screen1", any=[dict(description="Уведомление Система Android:"), dict(description="Уведомление RuStore: Самокат"), dict(description="Уведомление Обновление: Доступно обновление")])
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/layout_email_or_phone")], at=(0.5, 0.343))  # «layout_email_or_phone»
    ctx.type("66876947099")
    ctx.long_tap(0.498, 0.418, 0.8)
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/password_container")], at=(0.5, 0.245))  # «password_container»
    ctx.type("03SJDI5rNQAskJqs")
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/vk_toggle_button")], at=(0.907, 0.245))  # LinearLayout
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/vk_loading_btn_textView")], text=["Продолжить"], at=(0.5, 0.54))  # «Продолжить»
    ctx.click_target(sel=[dict(resourceId="not-robot-captcha-checkbox"), dict(description="Я не робот")], text=["Я не робот"], img="13_click.png", at=(0.498, 0.842))  # «Я не робот»
    ctx.expect_screen("screen4", any=[dict(resourceId="checkbox-modal-label"), dict(resourceId="not-robot-captcha-checkbox"), dict(description="Подтвердите, что вы не робот")])
    ctx.click_target(sel=[dict(resourceId="android:id/autofill_save_no"), dict(text="Никогда")], text=["Никогда"], img="15_click.png", at=(0.157, 0.947))  # «Никогда»
    ctx.click_target(sel=[dict(text="Далее")], at=(0.5, 0.931))  # View
    ctx.click_target(sel=[dict(text="Далее")], at=(0.5, 0.931))  # View
    ctx.click_target(sel=[dict(text="Далее")], at=(0.5, 0.931))  # View
    ctx.click_target(sel=[dict(text="Выйти")], text=["Выйти"], at=(0.906, 0.069))  # «Выйти»
    ctx.tap(0.9, 0.668)
    ctx.click_target(sel=[dict(description="Закрыть")], text=["Закрыть"], at=(0.902, 0.67))  # «Закрыть»
    ctx.stop_app("com.vkontakte.android")
    ctx.key("home")
    ctx.expect_screen("screen5", any=[dict(resourceId="com.mi.android.globallauncher:id/widget_container"), dict(resourceId="com.android.chrome:id/text_container"), dict(resourceId="com.android.chrome:id/microphone_icon")])
    ctx.click_target(sel=[dict(description="Страница 1. Итого страниц: 3")], text=["Страница 1. Итого страниц: 3"], at=(0.5, 0.834))  # «Страница 1. Итого страниц: 3»
