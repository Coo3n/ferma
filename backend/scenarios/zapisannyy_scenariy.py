"""Записано конструктором фермы 17.10.2026."""
RECORDED = True
NAME = "Записанный сценарий"


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.launch_app("com.wildberries.ru.dev")
    ctx.expect_screen("screen3", any=[dict(resourceId="MainBannersComponentContent"), dict(resourceId="horizontalPager"), dict(resourceId="bannerPage_1")])
    ctx.click_target(sel=[dict(text="Из китая")], text=["Из китая"], img="03_click.png", at=(0.112, 0.579))  # «Из китая»
    ctx.swipe(0.643, 0.889, 0.643, 0.748, 0.575)
    ctx.long_tap(0.665, 0.88, 0.8)
    ctx.expect_screen("screen5", any=[dict(resourceId="com.wildberries.ru.dev:id/snackbarCompose"), dict(resourceId="com.wildberries.ru.dev:id/bottomBarShadow"), dict(resourceId="com.wildberries.ru.dev:id/bottomBarCompose")])
    ctx.click_target(sel=[dict(text="Смартфоны")], text=["Смартфоны"], img="07_click.png", at=(0.125, 0.431))  # «Смартфоны»
    ctx.expect_screen("screen6", any=[dict(resourceId="newFastFiltersRow"), dict(resourceId="TopBarRoot"), dict(resourceId="back")])
    ctx.click_target(sel=[dict(className="android.view.View", instance=14), dict(resourceId="catalogGridCardShimmer")], img="09_click.png", at=(0.249, 0.44))  # «catalogGridCardShimmer»
