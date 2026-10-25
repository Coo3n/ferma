"""Черновик сценария по описанию словами.

Человек пишет задачу («открой Telegram, пролистай ленту»), нейросеть смотрит
на экран и предлагает шаги. Результат — ЧЕРНОВИК: он сохраняется как обычный
сценарий конструктора, который человек читает, правит и сам проверяет на
одном телефоне. Автоматического выполнения нет.

Ограничения те же, что у остальной нейросети фермы: выключена по умолчанию,
кадры уходят наружу только по согласию, секретные цели и защищённые экраны
отсекаются, вызовы идут в общий лимит. Модели разрешены только безопасные
виды шагов: `shell` и прочее, что меняет телефон вне приложения, — нет.
"""
from __future__ import annotations

import json
import re
import time

from .. import control
from ..recorder import steps as schema
from . import client, locate as loc, settings, usage

MAX_STEPS = 30
MAX_SLEEP = 60
JOB_KEY = "plan"
# Вид шага → обязательные поля. Числа 0..1 для координат; ограничения ниже.
ALLOWED = {
    "launch_app": ("package",),
    "open_url": ("url",),
    "tap": ("x", "y"),
    "swipe": ("x1", "y1", "x2", "y2"),
    "type": ("value",),
    "key": ("name",),
    "sleep": ("seconds",),
}
_COORDS = ("x", "y", "x1", "y1", "x2", "y2")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

PROMPT = (
    "You help to draft an automation recipe for an Android phone. The user's task: {task}\n"
    "Look at the screenshot (the current phone screen) and answer with ONLY a JSON array of steps, "
    "no explanations. Allowed step kinds and their args: {kinds}. "
    "Coordinates are fractions of the screen from 0 to 1. At most {limit} steps. "
    "Never include passwords, payment or personal data."
)


class PlanError(Exception):
    """Понятная причина, по которой черновика нет."""


def build_prompt(task: str) -> str:
    kinds = "; ".join(f'{k}({", ".join(args)})' for k, args in ALLOWED.items())
    return PROMPT.format(task=task.strip(), kinds=kinds, limit=MAX_STEPS)


def _number(value, lo, hi):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _clean(step):
    if not isinstance(step, dict) or step.get("kind") not in ALLOWED:
        return None
    args = step.get("args")
    if not isinstance(args, dict):
        return None
    kind, out = step["kind"], {}
    for name in ALLOWED[kind]:
        if name not in args:
            return None
        value = args[name]
        if name in _COORDS:
            value = _number(value, 0.0, 1.0)
        elif name == "seconds":
            value = _number(value, 0.0, MAX_SLEEP)
        else:
            value = str(value).strip()[:500]
            if not value:
                return None
        if value is None:
            return None
        out[name] = value
    return {"kind": kind, "args": out}


def parse_steps(text: str) -> list:
    """Шаги из ответа модели: только разрешённые виды, числа в границах."""
    raw = text or ""
    fenced = _FENCE.search(raw)
    body = fenced.group(1) if fenced else raw
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        raise PlanError("модель не вернула список шагов")
    try:
        items = json.loads(body[start:end + 1])
    except ValueError:
        raise PlanError("ответ модели не удалось прочитать")
    steps = [s for s in (_clean(i) for i in items) if s][:MAX_STEPS]
    if not steps:
        raise PlanError("в ответе модели нет подходящих шагов")
    return steps


def plan(serial: str, task: str) -> list:
    task = (task or "").strip()
    if not task:
        raise PlanError("опишите задачу словами")
    cfg = settings.get()
    if not (cfg.enabled and cfg.url):
        raise PlanError("нейросеть-помощник выключен — включите его в настройках (значок в шапке)")
    if loc.safety.secret_goal(task):
        raise PlanError("в описании пароль или платёжные данные — такое нейросети не отправляем")
    image = control.screenshot(serial, quality=85)

    class _C:       # screen_gate смотрит только на serial
        pass
    c = _C()
    c.serial = serial
    if loc.screen_gate(c, image):
        raise PlanError("экран защищён от снимков — нейросети его не показываем")
    ok, why = usage.reserve(JOB_KEY, cfg.max_per_job, cfg.max_per_day)
    if not ok:
        raise PlanError(why or "лимит запросов к нейросети на сегодня исчерпан")
    try:
        reply = client.ask(image, build_prompt(task))
    except Exception as e:  # noqa: BLE001
        usage.refund(JOB_KEY)           # ответа не было — квоту не тратим
        raise PlanError(f"нейросеть не ответила: {e}")
    return parse_steps(reply)


def recipe_for(task: str, steps: list) -> dict:
    """Тело для POST /api/recorder/save; проверку шагов делает сам конструктор."""
    title = " ".join(task.split())[:40]
    return {"key": time.strftime("chernovik_%Y%m%d_%H%M%S"),
            "meta": {"name": f"Черновик: {title}",
                     "description": "Составлен нейросетью по описанию. Проверьте шаги и запустите на одном телефоне.",
                     "watch_popups": True, "human": True},
            "params": {}, "steps": steps}
