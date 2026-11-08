"""Ревью и черновик сюжета текстовой моделью + строгая проверка ответов.

Ответ модели — только JSON; всё, что не проходит проверку, отбрасывается.
Координаты не выдумываются: в текстовом черновике нет tap/swipe по точкам.
"""
from __future__ import annotations

import json
import re

from ..recorder import steps as schema
from . import client, plan as vlm_plan, safety, settings

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
SEVERITY = ("high", "med", "low")
BASIS = ("analysis", "result", "assumption")
OPS = ("replace", "insert", "delete")


class ModelReplyError(Exception):
    """Ответ модели не разобрать (502)."""


def parse_json(text: str):
    raw = text or ""
    m = _FENCE.search(raw)
    body = (m.group(1) if m else raw).strip()
    try:
        return json.loads(body)
    except ValueError:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = body.find(a), body.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(body[i:j + 1])
            except ValueError:
                continue
    raise ModelReplyError("ответ модели не удалось прочитать (JSON неполный или отсутствует)")


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def validate_finding(raw, steps: list, n: int):
    """Finding или None. n — номер для id по умолчанию."""
    if not isinstance(raw, dict):
        return None
    idx = raw.get("steps")
    if not isinstance(idx, list) or not idx or not all(_int(i) is not None and 0 <= i < len(steps) for i in idx):
        return None
    if raw.get("severity") not in SEVERITY or raw.get("basis") not in BASIS:
        return None
    title, why = raw.get("title"), raw.get("why")
    if not (isinstance(title, str) and title.strip() and isinstance(why, str)):
        return None
    fix = raw.get("fix")
    if fix is not None:
        if not isinstance(fix, dict) or fix.get("op") not in OPS:
            return None
        i = _int(fix.get("index"))
        if i is None or not (0 <= i < len(steps) or (fix["op"] == "insert" and i == len(steps))):
            return None
        out = {"op": fix["op"], "index": i}
        if fix["op"] != "delete":
            try:
                out["step"] = schema.normalize_step(fix.get("step"))
            except schema.StepError:
                return None
        fix = out
    fid = raw.get("id")
    return {"id": str(fid)[:40] if fid else f"f{n + 1}", "steps": [int(i) for i in dict.fromkeys(idx)],
            "severity": raw["severity"], "title": title.strip()[:200], "why": why.strip()[:1000],
            "basis": raw["basis"], "fix": fix}


def validate_findings(items, steps: list) -> tuple[list, int]:
    if not isinstance(items, list):
        raise ModelReplyError("в ответе модели нет списка замечаний")
    good, dropped = [], 0
    for k, it in enumerate(items):
        f = validate_finding(it, steps, k)
        if f is None:
            dropped += 1
        else:
            good.append(f)
    return good, dropped


FINDING_SPEC = (
    'Finding: {"id":"f1","steps":[0-based step indexes, non-empty],"severity":"high|med|low",'
    '"title":"short","why":"reason","basis":"analysis|result|assumption",'
    '"fix":null or {"op":"replace|insert|delete","index":int,"step":{"kind":..,"args":{..}}}}. '
    "Step kinds: " + ", ".join(sorted(schema.ARGS)) + ". Never invent coordinates.")


def numbered(steps: list) -> str:
    return "\n".join(f"{i}: {json.dumps(s, ensure_ascii=False)}" for i, s in enumerate(steps))


_NEEDS_WAIT = {"launch_app", "open_url", "tap", "click", "swipe"}
_WAITS = {"sleep", "wait"}


def rule_findings(steps: list) -> list:
    """Надёжные замечания без нейросети: маленькая модель отвечает общими фразами, а эти
    два случая видны прямо по шагам. Исправление — только вставка паузы; координаты и
    селекторы не выдумываем (нажатие по точке просто помечаем)."""
    out = []
    for i, s in enumerate(steps):
        kind = s.get("kind") if isinstance(s, dict) else None
        args = (s.get("args") or {}) if isinstance(s, dict) else {}
        if kind == "tap" and not s.get("selector") and not s.get("texts") and "x" in args and "y" in args:
            out.append({"id": f"r-coord-{i}", "steps": [i], "severity": "med", "basis": "analysis",
                        "title": "Нажатие по координатам",
                        "why": "Шаг нажимает в точку экрана. На другом телефоне, языке или после обновления "
                               "приложения кнопка окажется в другом месте. Лучше найти её по тексту — "
                               "перезапишите шаг через «Как искать» в конструкторе.",
                        "fix": None})
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        if kind in _NEEDS_WAIT and isinstance(nxt, dict) and nxt.get("kind") not in _WAITS:
            try:
                pause = schema.normalize_step({"kind": "sleep", "args": {"seconds": 1.5}})
            except schema.StepError:
                continue
            out.append({"id": f"r-wait-{i}", "steps": [i, i + 1], "severity": "low", "basis": "analysis",
                        "title": "Нет ожидания после действия",
                        "why": "Следующий шаг начнётся сразу, а экран мог ещё не загрузиться: на медленном "
                               "телефоне нажатие уйдёт «в пустоту». Добавьте паузу между шагами.",
                        "fix": {"op": "insert", "index": i + 1, "step": pause}})
    return out


def review(steps: list) -> tuple[list, int]:
    found, dropped = _review_model(steps)
    seen = {(tuple(f["steps"]), f["fix"] and f["fix"]["op"]) for f in found}
    mine = [f for f in rule_findings(steps) if (tuple(f["steps"]), f["fix"] and f["fix"]["op"]) not in seen]
    return mine + found, dropped


def _review_model(steps: list) -> tuple[list, int]:
    prompt = ("Review this Android automation scenario for mistakes, missing waits, fragile steps and "
              "risky actions. Answer ONLY with JSON {\"findings\": [Finding, ...]}. "
              "Write title and why in Russian. " + FINDING_SPEC
              + "\nSteps:\n" + numbered(steps))
    try:
        reply = client.chat([{"role": "user", "content": prompt}], max_tokens=2000)
    except client.VlmError as e:
        raise ModelReplyError(f"нейросеть не ответила: {e}")
    data = parse_json(reply)
    items = data.get("findings") if isinstance(data, dict) else data
    return validate_findings(items, steps)


# ---- черновик только из текста ----
TEXT_KINDS = {"launch_app", "open_url", "type", "key", "sleep", "click", "stop_app", "wait"}


def _text_step(raw):
    """Шаг текстового черновика: click — только по тексту кнопки (селектор text="..."),
    без координат; остальное по схеме recorder."""
    if not isinstance(raw, dict) or raw.get("kind") not in TEXT_KINDS:
        return None
    if raw["kind"] == "click":
        text = str((raw.get("args") or {}).get("text") or raw.get("text") or "").strip()
        if not text or '"' in text or "\\" in text or len(text) > 80:
            return None
        raw = {"kind": "click", "args": {}, "texts": [text],
               "selector": {"call": "click", "args": f'text="{text}"'}}
    if raw["kind"] == "key":
        from ..control.input import KEYCODES  # только реальные клавиши: не «back|home|enter» из подсказки
        name = str((raw.get("args") or {}).get("name") or "").strip().lower()
        if name not in KEYCODES:
            return None
        raw = {**raw, "args": {**(raw.get("args") or {}), "name": name}}
    try:
        return schema.normalize_step(raw)
    except schema.StepError:
        return None


def draft_text(task: str, answers: list | None) -> dict:
    cfg = settings.get()
    full = task.strip() + ("\nClarifications: " + "; ".join(a for a in (answers or []) if a) if answers else "")
    prompt = ("Draft an Android automation scenario WITHOUT seeing the screen. Task: " + full + "\n"
              "Answer ONLY with JSON: either {\"questions\": [\"...\"]} if the task is too vague to proceed "
              "(max 3 questions), or {\"steps\": [...], \"notes\": [\"...\"]}. Allowed steps: "
              '{"kind":"launch_app","args":{"package":".."}}, {"kind":"open_url","args":{"url":".."}}, '
              '{"kind":"type","args":{"value":".."}}, {"kind":"key","args":{"name":"home"}} (name is one of: back, home, enter, recents), '
              '{"kind":"sleep","args":{"seconds":n}}, {"kind":"click","args":{"text":"button label"}}. '
              "Do NOT use coordinates: if a target cannot be named by its text, ask a question. "
              "At most 30 steps. No passwords or payment data. Cover the WHOLE task, not only the first "
              "step. Write every question and note in Russian.")
    try:
        reply = client.chat([{"role": "user", "content": prompt}], cfg=cfg, max_tokens=1800)
    except client.VlmError as e:
        raise ModelReplyError(f"нейросеть не ответила: {e}")
    data = parse_json(reply)
    if not isinstance(data, dict):
        raise ModelReplyError("ответ модели не в ожидаемом формате")
    qs = [str(q).strip() for q in data.get("questions") or [] if str(q).strip()][:3] if isinstance(
        data.get("questions"), list) else []
    if qs and not data.get("steps"):
        return {"status": "questions", "questions": qs}
    raw = data.get("steps")
    if not isinstance(raw, list):
        raise ModelReplyError("в ответе модели нет списка шагов")
    steps = [s for s in (_text_step(r) for r in raw[:vlm_plan.MAX_STEPS]) if s]
    if not steps:
        if qs:
            return {"status": "questions", "questions": qs}
        raise ModelReplyError("в ответе модели нет подходящих шагов")
    notes = [str(n)[:300] for n in data.get("notes") or [] if isinstance(n, str)][:5] if isinstance(
        data.get("notes"), list) else []
    if len(steps) < len(raw):
        notes.append("Часть шагов отброшена: они требовали координат или были недопустимы.")
    return {"status": "steps", "steps": steps, "notes": notes, "needs_screen": True}


# ---- рискованные шаги ----
_PASS = re.compile(r"парол|password|passwd|pin\b|пин-?код|cvv|cvc|карт", re.I)


def risky_steps(steps: list) -> list:
    out = []
    for i, s in enumerate(steps):
        args = s.get("args") or {}
        texts = [str(args.get("value") or ""), str(s.get("note") or ""), *(s.get("texts") or []),
                 str((s.get("selector") or {}).get("args") or ""), str(args.get("url") or ""),
                 str(args.get("name") or "")]
        cls = safety.irreversible(*texts)
        if cls:
            out.append({"index": i, "reason": f"похоже на необратимое действие ({cls})"})
        elif s.get("kind") == "type" and (args.get("field") == "password" or _PASS.search(" ".join(texts))):
            out.append({"index": i, "reason": "ввод пароля или платёжных данных"})
        elif s.get("kind") == "shell":
            out.append({"index": i, "reason": "команда shell меняет телефон вне приложения"})
    return out
