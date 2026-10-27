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
from ..ui import tree
from . import client, locate as loc, settings, usage

MODEL_SCALE = 1000.0     # шкала координат в ответе модели; в сценарии — доли 0..1
MAX_STEPS = 30
MAX_SLEEP = 60
# Черновик на 30 шагов не помещается в 300 токенов обычной подсказки.
PLAN_MAX_TOKENS = 1800
# Вид шага → обязательные поля. В сценарии координаты — доли 0..1; ограничения ниже.
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
    "Look at the screenshot (the current phone screen) and answer with ONLY a JSON array of steps "
    "(an array even for one step) that covers the WHOLE task, not only the first step, "
    "no explanations. Every step has exactly this shape: "
    '{{"kind": "<kind>", "args": {{...}}}}, for example '
    '[{{"kind": "launch_app", "args": {{"package": "com.android.chrome"}}}}, '
    '{{"kind": "tap", "args": {{"x": 500, "y": 300}}}}]. '
    "Allowed step kinds and their args: {kinds}. "
    "Coordinates are integers from 0 to 1000 (0,0 = top-left, 1000,1000 = bottom-right). "
    "To open an app use launch_app with its Android package name (for example com.android.settings, "
    "com.android.chrome, com.miui.calculator) instead of searching for its icon. "
    "Never repeat the same step more than twice in a row. "
    "At most {limit} steps. Never include passwords, payment or personal data."
)


class PlanError(Exception):
    """Понятная причина, по которой черновика нет."""


class UnreadableReply(PlanError):
    """Ответ модели обрезан или не JSON: запрос зря, квоту возвращаем."""


def build_prompt(task: str) -> str:
    kinds = "; ".join(f'{k}({", ".join(args)})' for k, args in ALLOWED.items())
    return PROMPT.format(task=task.strip(), kinds=kinds, limit=MAX_STEPS)


def _number(value, lo, hi):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, n))


def _from_model(value):
    """Координата ответа модели 0..1000 → доля 0..1; вне шкалы или не число → None."""
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n / MODEL_SCALE if 0 <= n <= MODEL_SCALE else None


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
            value = _from_model(value)
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
        a, b = body.find("{"), body.rfind("}")      # модель иногда шлёт один шаг без массива
        if a < 0 or b <= a:
            raise UnreadableReply("модель не вернула список шагов (ответ мог оборваться)")
        body = "[" + body[a:b + 1] + "]"
        start, end = 0, len(body) - 1
    try:
        items = json.loads(body[start:end + 1])
    except ValueError:
        raise UnreadableReply("ответ модели не удалось прочитать")
    steps = []
    for i in items:
        step = _clean(i)
        # Три одинаковых шага подряд — зацикливание модели, лишние не берём.
        if step and not (len(steps) >= 2 and steps[-1] == step and steps[-2] == step):
            steps.append(step)
    steps = steps[:MAX_STEPS]
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
    if loc.is_autoglm(cfg.model):
        raise PlanError("AutoGLM ведёт телефон по одному шагу и не составляет сценарий целиком "
                        "по одному экрану — запустите ИИ-агента или выберите в настройках Qwen3-VL")
    if loc.safety.secret_goal(task):
        raise PlanError("в описании пароль или платёжные данные — такое нейросети не отправляем")
    try:
        image = control.screenshot(serial, quality=85)
    except Exception as e:  # noqa: BLE001 — офлайн или неизвестный телефон
        raise PlanError(f"не удалось снять экран телефона: {e}")
    # Как в locate: на экране с полем пароля или кода кадр наружу не уходит.
    try:
        w, h = control.size(serial)
        nodes = tree.parse(control.dump_hierarchy(serial), w, h)
    except Exception as e:  # noqa: BLE001
        raise PlanError(f"не удалось прочитать экран телефона: {e}")
    if nodes and loc.safety.secret_screen(nodes):
        raise PlanError("на экране поле пароля или кода — такой кадр нейросети не отправляем")

    class _C:       # screen_gate смотрит только на serial
        pass
    c = _C()
    c.serial = serial
    if loc.screen_gate(c, image):
        raise PlanError("экран защищён от снимков — нейросети его не показываем")
    # Пустой ключ: потолок «на задачу» не применяется (каждый черновик — своя
    # задача), действует только суточный лимит.
    ok, why = usage.reserve("", cfg.max_per_job, cfg.max_per_day)
    if not ok:
        raise PlanError(why or "лимит запросов к нейросети на сегодня исчерпан")
    try:
        reply = client.ask(image, build_prompt(task), max_tokens=PLAN_MAX_TOKENS)
    except Exception as e:  # noqa: BLE001
        usage.refund("")                # ответа не было — квоту не тратим
        raise PlanError(f"нейросеть не ответила: {e}")
    try:
        return parse_steps(reply)
    except UnreadableReply:
        usage.refund("")                # обрыв или мусор вместо JSON — тоже не в счёт
        raise


def recipe_for(task: str, steps: list) -> dict:
    """Тело для POST /api/recorder/save; проверку шагов делает сам конструктор."""
    title = " ".join(task.split())[:40]
    return {"key": time.strftime("chernovik_%Y%m%d_%H%M%S"),
            "meta": {"name": f"Черновик: {title}",
                     "description": "Составлен нейросетью по описанию. Проверьте шаги и запустите на одном телефоне.",
                     "watch_popups": True, "human": True},
            "params": {}, "steps": steps}
