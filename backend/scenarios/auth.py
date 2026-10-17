"""Записано конструктором фермы 26.09.2026."""
RECORDED = True
NAME = "auth"


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.launch_app("com.wildberries.ru.dev")
    ctx.expect_screen("screen8", any=[dict(resourceId="MainBannersComponentContent"), dict(resourceId="horizontalPager"), dict(resourceId="bannerPage_8")])
    ctx.click_target(sel=[dict(description="Профиль")], text=["Профиль"], img="03_click.png", at=(0.875, 0.939))  # «Профиль»
    ctx.expect_screen("screen9", any=[dict(resourceId="unauthorizedScreenImage"), dict(resourceId="unauthorizedScreenTitle"), dict(resourceId="unauthorizedScreenDescription")])
    ctx.click_target(sel=[dict(resourceId="unauthorizedScreenEnterProfileButtonTitle"), dict(text="Войти в профиль")], text=["Войти в профиль"], img="05_click.png", at=(0.5, 0.548))  # «Войти в профиль»
    ctx.sleep(3.5)
    ctx.expect_screen("Ввод телефона", any=[dict(resourceId="PhoneInput"), dict(resourceId="getCodeButton"), dict(resourceId="com.wildberries.ru.dev:id/snackbarCompose")])
    ctx.type("0008984606")
    ctx.expect_screen("screen11", any=[dict(resourceId="PhoneInput"), dict(resourceId="getCodeButton"), dict(resourceId="com.wildberries.ru.dev:id/snackbarCompose")])
    ctx.click_target(sel=[dict(resourceId="getCodeButton")], img="10_click.png", at=(0.5, 0.59))  # «getCodeButton»
    ветка = ctx.which_screen({
        "03:31": [dict(resourceId="com.android.systemui:id/status_bar_launch_animation_container"), dict(resourceId="com.android.systemui:id/status_bar_container"), dict(resourceId="com.android.systemui:id/status_bar")],
    })
