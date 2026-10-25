"""Подсказка человеку, когда задача встала: что на экране и что мешает.

Одна короткая фраза в карточку «Ждёт». Те же лимиты и выключатель, что у
слоя поиска; любая ошибка гасится — подсказка украшение, HELD она ломать не
вправе. Вызов идёт в фоновом потоке: ответ модели может занять секунды, а
человеку карточка нужна сразу.
"""
from __future__ import annotations

import logging
import threading

from .. import control
from . import client, locate as loc, settings, usage

log = logging.getLogger("farm.vlm")

PROMPT = (
    "An automated script on an Android phone is stuck. The step it could not do: {what}\n"
    "Look at the screenshot and answer in RUSSIAN, in at most 2 short sentences, "
    "plain words without technical jargon: what is on the screen now and what most "
    "likely prevents the step. No lists, no JSON."
)
MAX_LEN = 400


def advise(serial: str, what: str, job_key: str = "") -> str:
    """Текст подсказки или '' (выключено, лимит, защищённый экран, ошибка)."""
    try:
        cfg = settings.get()
        if not (cfg.enabled and cfg.url):
            return ""
        if loc.safety.secret_goal(what):
            return ""
        image = control.screenshot(serial, quality=85)
        class _C:   # screen_gate смотрит только на serial
            pass
        c = _C()
        c.serial = serial
        if loc.screen_gate(c, image):
            return ""
        ok, _ = usage.reserve(job_key, cfg.max_per_job, cfg.max_per_day)
        if not ok:
            return ""
        try:
            text = client.ask(image, PROMPT.format(what=what)).strip()
        except Exception:
            usage.refund(job_key)   # ответа не было — квоту не тратим
            raise
        return " ".join(text.split())[:MAX_LEN]
    except Exception as e:  # noqa: BLE001 — подсказка никогда не ломает HELD
        log.info("подсказка нейросети не получилась: %s", e)
        return ""


def start(job, what: str) -> threading.Thread | None:
    """Запустить подсказку в фоне; результат — в job.held_hint, если задача
    всё ещё стоит на том же вопросе."""
    if not settings.enabled():
        return None
    stamp = job.held_at

    def work():
        text = advise(job.serial, what, job.id)
        if text and job.held_at == stamp and job.held_reason:
            job.held_hint = text
            try:
                job.add_line(f"нейросеть: {text}")
            except Exception:  # noqa: BLE001
                pass

    th = threading.Thread(target=work, name="vlm-advise", daemon=True)
    th.start()
    return th
