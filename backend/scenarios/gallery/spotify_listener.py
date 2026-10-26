"""Spotify: ищет слово, запускает первый трек, слушает, лайкает по шансу.

Идентификаторы `com.spotify.music:id/...` взяты из скрипта Laixi (версия ver520)
и могут отличаться в вашей версии приложения. Режимы прослушивания: целиком
(пока не сменится название) или диапазон секунд со случайной перемоткой.
"""
import random

from farm import story

NAME = "Spotify: слушатель (по списку)"
DESCRIPTION = "Ищет слова, запускает первый трек, слушает целиком или заданное время, лайкает по шансу."
PACKAGE = "com.spotify.music"
STEPS = [
    "Открыть Spotify",
    "Взять первое слово из вашего списка",
    "Открыть вкладку поиска и ввести слово",
    "Подождать результаты и открыть первый трек",
    "Иногда ставить лайк треку, но не больше потолка за сутки",
    "Слушать трек целиком или заданное число секунд, иногда с перемоткой",
    "Перейти к следующему слову списка и повторить",
]
GALLERY = {"platform": "Spotify", "verified": False, "package": PACKAGE}
ID = PACKAGE + ":id/"
LISTEN_FULL = "Целиком"
LISTEN_RANGE = "Диапазон секунд"
PARAMS = {
    "words": {"label": "Слова поиска (по строке)", "type": "textarea", "default": ""},
    "mode": {"label": "Как слушать", "options": [LISTEN_FULL, LISTEN_RANGE], "default": LISTEN_FULL},
    "range_lo": {"label": "Диапазон от, с", "type": "number", "default": 30, "min": 5},
    "range_hi": {"label": "Диапазон до, с", "type": "number", "default": 90, "min": 6},
    "max_minutes": {"label": "Трек целиком — не дольше, мин", "type": "number", "default": 6, "min": 1, "max": 60},
    "like": {"label": "Шанс лайка, %", "type": "number", "default": 20, "min": 0, "max": 100},
    "cap_like": {"label": "Не больше лайков за сутки", "type": "number", "default": 100, "min": 0},
}


def _center(el):
    left, top, right, bottom = el.bounds()
    return (left + right) // 2, (top + bottom) // 2


def search(ctx, word):
    ctx.click_target(sel=[dict(resourceId=ID + "search_tab")], timeout=8)
    ctx.click_target(sel=[dict(resourceId=ID + "find_search_field")], timeout=8)
    ctx.set_text(word, timeout=8, resourceId=ID + "query")
    ctx.pause(2, 5)
    return ctx.exists(timeout=4, resourceId=ID + "search_body")


def open_first_track(ctx):
    row = ctx.find(timeout=4, resourceId=ID + "row_root")
    if row is None:
        return False
    x, y = _center(row)
    ctx.tap(x - 200, y)       # левее «⋯», чтобы не открыть меню строки
    ctx.pause(1, 3)
    return True


def maybe_like(ctx, rate, cap):
    if cap > 0 and ctx.chance(rate):
        ctx.budget("Spotify: лайки", cap, "spotify")
        ctx.click_target(sel=[dict(resourceId=ID + "add_to_button")], timeout=4)
        ctx.sleep(1)
        if "PageActivity" in ctx.shell("dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'"):
            ctx.back()     # открылся список плейлистов — лайк уже поставлен


def listen_full(ctx, max_minutes):
    title = ctx.find(timeout=3, resourceId=ID + "track_info_view_title")
    if title is None:
        ctx.log("название трека не нашёл — слушаю 60 секунд")
        ctx.sleep(60)
        return
    first = title.get_text()
    for _ in range(int(max_minutes * 30)):               # опрос раз в 2 с
        ctx.sleep(2)
        now = ctx.find(timeout=2, resourceId=ID + "track_info_view_title")
        if now is not None and now.get_text() != first:
            ctx.log("трек сменился — следующее слово")
            return
    ctx.log("трек не сменился за лимит времени — иду дальше")


def listen_range(ctx, lo, hi, rng):
    ctx.click_target(sel=[dict(resourceId=ID + "cover_image")], timeout=4)
    ctx.sleep(1)
    total = rng.randint(int(lo), int(hi))
    bar = ctx.find(timeout=2, resourceId=ID + "seekbar", className="android.widget.SeekBar") \
        if ctx.chance(40) else None
    plan = story.seek_plan(total, 3, 8, rng)
    ctx.log(f"слушаю {total} с" + (", с перемоткой" if bar is not None else ""))
    for step in plan:
        if bar is not None:
            left, top, right, bottom = bar.bounds()
            y = (top + bottom) // 2
            ctx.swipe(rng.randint(left, right), y, rng.randint(left, right), y, 0.9)
        ctx.sleep(step)
    ctx.back()


def run(ctx):
    words = story.parse_lines(ctx.params["words"], 200)
    if not words:
        ctx.fail("список слов пуст")
    if ctx.params["mode"] == LISTEN_RANGE and float(ctx.params["range_lo"]) >= float(ctx.params["range_hi"]):
        ctx.fail("Диапазон «от» должен быть меньше «до»")
    ctx.watch_popups()
    ctx.humanize()
    ctx.unlock()
    ctx.launch_app(PACKAGE)
    if not ctx.wait_app(PACKAGE, timeout=20):
        ctx.fail("Spotify не открылся")
    rng = random.Random()
    rate = float(ctx.params["like"])
    cap = int(ctx.params["cap_like"])
    for i, word in enumerate(words, 1):
        ctx.log(f"слово {i} из {len(words)}: «{word}»")
        if not search(ctx, word) or not open_first_track(ctx):
            ctx.log("результатов нет — следующее слово")
            continue
        maybe_like(ctx, rate, cap)
        if ctx.params["mode"] == LISTEN_RANGE:
            listen_range(ctx, ctx.params["range_lo"], ctx.params["range_hi"], rng)
        else:
            listen_full(ctx, float(ctx.params["max_minutes"]))
