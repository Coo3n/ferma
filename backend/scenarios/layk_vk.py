"""Записано конструктором фермы 20.09.2026."""
RECORDED = True
NAME = "Лайк ВК"


def run(ctx):
    ctx.watch_popups()
    ctx.humanize()
    ctx.launch_app("com.vkontakte.android")
    ctx.expect_screen("Главная", any=[dict(resourceId="com.vkontakte.android:id/app_bar_layout"), dict(resourceId="com.vkontakte.android:id/header_container"), dict(resourceId="com.vkontakte.android:id/user_photo")])
    ctx.swipe(0.71, 0.886, 0.64, 0.438, 0.44)
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/tab_clips"), dict(description="Клипы")], text=["Клипы"], img="04_click.png", at=(0.584, 0.956))  # «Клипы»
    ctx.expect_screen("screen5", any=[dict(resourceId="com.vkontakte.android:id/clips_wrapper_top_bar"), dict(resourceId="com.vkontakte.android:id/clips_header_view"), dict(resourceId="com.vkontakte.android:id/clips_header_content")])
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/fullscreen_clip_overlay_like_text"), dict(text="3")], text=["3"], img="06_click.png", at=(0.921, 0.554))  # «3»
    ctx.swipe(0.476, 0.765, 0.615, 0.151, 0.441)
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/fullscreen_clip_overlay_comment_container"), dict(description="23 комментария")], text=["23 комментария"], img="08_click.png", at=(0.921, 0.625))  # «23 комментария»
    ctx.long_tap(0.413, 0.614, 0.8)
    ctx.expect_screen("screen6", any=[dict(resourceId="com.android.systemui:id/status_bar_launch_animation_container"), dict(resourceId="com.android.systemui:id/status_bar_container"), dict(resourceId="com.android.systemui:id/status_bar")])
    ctx.tap(0.594, 0.61)
    ctx.expect_screen("screen7", any=[dict(resourceId="com.android.systemui:id/status_bar_launch_animation_container"), dict(resourceId="com.android.systemui:id/status_bar_container"), dict(resourceId="com.android.systemui:id/status_bar")])
    ctx.click_target(sel=[dict(description="Закрыть")], text=["Закрыть"], img="13_click.png", at=(0.069, 0.277))  # «Закрыть»
    ctx.swipe(0.58, 0.743, 0.58, 0.375, 0.236)
    ctx.swipe(0.661, 0.784, 0.713, 0.231, 0.37)
    ctx.expect_screen("screen8", any=[dict(resourceId="com.vkontakte.android:id/clips_wrapper_top_bar"), dict(resourceId="com.vkontakte.android:id/clips_header_view"), dict(resourceId="com.vkontakte.android:id/clips_header_content")])
    ctx.click_target(sel=[dict(resourceId="com.vkontakte.android:id/fullscreen_clip_overlay_like_container"), dict(description="14787 лайков")], text=["14787 лайков"], img="17_click.png", at=(0.921, 0.554))  # «14787 лайков»
    ctx.stop_app("com.vkontakte.android")
