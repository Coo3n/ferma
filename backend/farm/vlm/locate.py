"""Шестой слой резолвера: нейросеть смотрит на кадр и указывает, куда нажать.

Зовётся, когда дешёвые слои (селектор, текст, OCR, шаблон) промахнулись, и
ПЕРЕД слоем «точка»: точка слепа (помнит место, но не видит экран), нейросеть
видит. Поэтому тап вслепую, о котором иначе пришлось бы спрашивать человека,
заменяется осознанным попаданием. Модель возвращает относительные координаты
0–1000 (контракт Open-AutoGLM), здесь они переводятся в доли 0..1.

Порядок защит: выключатель → цель не про необратимое и не про пароль → на
экране нет поля пароля → кадр не защищён → квота → вызов → порог уверенности →
под найденной точкой нет необратимого. Любой отказ — None, и дальше всё идёт
как без нейросети (точка с вопросом человеку, потом HELD).
"""
from __future__ import annotations

import logging

from .. import control, deviations as dv
from ..ui import tree
from . import client, learn, safety, settings, usage
from .parse import parse

log = logging.getLogger("farm.vlm")

POINT_RADIUS = 0.06      # доля экрана вокруг точки, где читаем надписи
PROMPT = (
    "You are looking at an Android phone screenshot. Find the ONE element a user "
    "should tap to achieve this goal: {goal}\n"
    "Visible texts on screen (may help): {summary}\n"
    "Reply with JSON only, no other text. If found: "
    '{{"x": 0..1000, "y": 0..1000, "confidence": 0..1, "why": "short reason"}} '
    "where x,y is the CENTER of the element in relative coordinates "
    "(0,0 = top-left, 1000,1000 = bottom-right). "
    'If the element is not on the screen: {{"found": false, "why": "short reason"}}. '
    "Never guess."
)

# AutoGLM обучена отвечать <think>…</think><answer>do(…)</answer> и JSON не слушается:
# рассуждает до обрыва. Этот промпт держит рассуждение коротким и ответ в её формате.
AUTOGLM_PROMPT = (
    "You are an Android operation agent. Goal: tap {goal}.\n"
    "Visible texts on screen (may help): {summary}\n"
    "Respond in this exact format, with a SHORT think (max 15 words):\n"
    "<think>short reason</think>\n"
    '<answer>do(action="Tap", element=[x,y])</answer>\n'
    "x,y are relative coordinates 0-999 of the element center (0,0 = top-left).\n"
    'If the element is not on the screen: <answer>do(action="NotFound")</answer>'
)
AUTOGLM_MAX_TOKENS = 400


def is_autoglm(model: str) -> bool:
    return "autoglm" in (model or "").lower()


def goal_texts(what: dict) -> list:
    """Всё, что говорит, ЧТО просили нажать: тексты, значения селекторов, подпись шага."""
    out = [str(t) for t in (what.get("text") or [])]
    for s in what.get("sel") or []:
        if isinstance(s, dict):
            out += [str(v) for k, v in s.items() if isinstance(v, str)
                    and k in ("text", "textContains", "description", "descriptionContains",
                              "resourceId")]
    if what.get("label"):
        out.append(str(what["label"]))
    return [t for t in out if t.strip()]


def _log(ctx, msg: str) -> None:
    try:
        ctx.log(msg)
    except Exception:  # noqa: BLE001
        log.info(msg)


def _nodes(ctx):
    try:
        w, h = ctx.size
        return tree.parse(ctx.dump_hierarchy(), w, h)
    except Exception:  # noqa: BLE001 — дерево недоступно: без него и без OCR идём осторожно
        return None


def summary_of(nodes, limit: int = 40) -> str:
    seen, out = set(), []
    for n in nodes or []:
        for t in (n.text, n.description):
            t = (t or "").strip()
            if t and t not in seen and len(t) <= 60:
                seen.add(t)
                out.append(t)
    return "; ".join(out[:limit])


def texts_at(nodes, x: float, y: float, ocr_items=()) -> list:
    """Надписи под точкой и рядом: дерево и (если есть) OCR."""
    out = []
    for n in nodes or []:
        x1, y1, x2, y2 = n.bounds
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        covers = x1 <= x <= x2 and y1 <= y <= y2 and n.area <= 0.25
        near = abs(cx - x) <= POINT_RADIUS and abs(cy - y) <= POINT_RADIUS
        if covers or near:
            out += [n.text, n.description, n.resource_id]
    for text, cx, cy in ocr_items:
        if abs(cx - x) <= POINT_RADIUS * 1.5 and abs(cy - y) <= POINT_RADIUS * 1.5:
            out.append(text)
    return [t for t in out if t]


def _ocr_items(image: bytes) -> list:
    try:
        from ..vision import ocr
        if not ocr.backend():
            return []
        return [(b.text, b.cx, b.cy) for b in ocr.ocr(image)]
    except Exception:  # noqa: BLE001
        return []


def _record(ctx, kind, title, detail, signature) -> None:
    try:
        dv.deviations.record(
            kind=kind, title=title, detail=detail,
            device_name=getattr(ctx, "device_name", ""), job_id=getattr(ctx, "job_id", ""),
            scenario_key=getattr(ctx, "scenario_key", ""),
            scenario_name=getattr(ctx, "scenario_name", ""), signature=signature)
    except Exception as e:  # noqa: BLE001 — запись не роняет шаг
        log.warning("отклонение нейросети не записалось: %s", e)


def job_key(ctx) -> str:
    return getattr(ctx, "job_id", "") or f"ctx-{id(ctx)}"


def screen_gate(ctx, image: bytes) -> str:
    """Причина не отправлять кадр или ''. Защищённый экран — чёрный квадрат, он
    ничего не скажет, а флаг от захвата дешевле пустого платного вызова."""
    try:
        if control.is_secure(ctx.serial):
            return "экран защищён от снимков"
    except Exception:  # noqa: BLE001
        pass
    try:
        if control.is_blank(image):
            return "кадр пустой (чёрный)"
    except Exception:  # noqa: BLE001
        pass
    return ""


def locate(ctx, what: dict, tree_summary: str = ""):
    """Hit(layer="vlm") или None. Не бросает: нейросеть — подсобный слой."""
    from ..resolve import Hit
    cfg = settings.get()
    if not (cfg.enabled and cfg.url):
        return None
    try:
        goals = goal_texts(what)
        if not goals:
            return None
        if safety.secret_goal(*goals):
            _log(ctx, "нейросеть не зову: цель связана с паролем, кодом или картой")
            return None
        bad = safety.irreversible(*goals)
        if bad:
            _refuse(ctx, goals, bad, "цель шага")
            return None
        nodes = _nodes(ctx)
        if nodes and safety.secret_screen(nodes):
            _log(ctx, "нейросеть не зову: на экране поле пароля или кода")
            return None
        image = ctx.screen_bytes()
        why_not = screen_gate(ctx, image)
        if why_not:
            _log(ctx, f"нейросеть не зову: {why_not}")
            return None
        ok, reason = usage.reserve(job_key(ctx), cfg.max_per_job, cfg.max_per_day)
        if not ok:
            _log(ctx, f"нейросеть не зову: {reason}")
            return None
        goal = "; ".join(goals)
        auto = is_autoglm(cfg.model)
        prompt = (AUTOGLM_PROMPT if auto else PROMPT).format(
            goal=goal, summary=tree_summary or summary_of(nodes) or "unknown")
        try:
            reply = (client.ask(image, prompt, max_tokens=AUTOGLM_MAX_TOKENS) if auto
                     else client.ask(image, prompt))
        except Exception as e:  # noqa: BLE001
            usage.refund(job_key(ctx))   # ответа не было — квоту не тратим
            _log(ctx, f"нейросеть не ответила: {e}")
            return None
        ans = parse(reply)
        if ans is None:
            _log(ctx, "нейросеть не нашла цель на экране или ответила невнятно")
            return None
        if ans.confidence < cfg.min_confidence:
            _log(ctx, f"нейросеть подсказала место, но уверенность {ans.confidence:.2f} "
                      f"ниже порога {cfg.min_confidence:.2f} — не верю")
            return None
        under = texts_at(nodes, ans.x, ans.y, _ocr_items(image))
        if not under:
            # Ни дерева, ни OCR под точкой: проверять denylist нечем. Без
            # проверки точку не принимаем — по умолчанию осторожность.
            _refuse(ctx, ["нет текста под точкой"], "не проверено",
                    "надпись под найденной точкой не удалось прочитать")
            return None
        bad = safety.irreversible(*under)
        if bad:
            _refuse(ctx, under, bad, "надпись под найденной точкой")
            return None
        _log(ctx, f"нейросеть подсказала точку ({ans.x:.2f}, {ans.y:.2f}), "
                  f"уверенность {ans.confidence:.2f}: {ans.why}")
        _learn(ctx, what, nodes, ans)
        return Hit(ans.x, ans.y, "vlm", f"уверенность {ans.confidence:.2f}: {ans.why}")
    except Exception as e:  # noqa: BLE001
        log.warning("слой нейросети упал: %s", e)
        return None


def _refuse(ctx, texts, bad: str, where: str) -> None:
    _log(ctx, f"нейросеть не нажимает необратимое («{bad}», {where}) — решит человек")
    _record(ctx, dv.VLM_DENIED,
            f"нейросеть отказалась: действие «{bad}» необратимо",
            "Цель похожа на необратимое действие (оплата, отправка, удаление, выход, "
            "подписка). Такое нейросеть не нажимает — решите сами в окне ожидания.",
            f"denied|{bad}|{'/'.join(texts)[:80]}")


def _learn(ctx, what: dict, nodes, ans) -> None:
    """Запомнить найденное, чтобы остальные телефоны обошлись без нейросети."""
    sel = learn.selector_for_point(nodes, ans.x, ans.y) if nodes else None
    k = what.get("key") or ""
    n = 0
    if sel:
        ctx.vlm_patch = {"sel": [sel]}
        if k:
            try:
                n = learn.remember(k, [sel], getattr(ctx, "scenario_key", ""))
            except Exception as e:  # noqa: BLE001
                log.warning("не удалось запомнить селектор: %s", e)
        _log(ctx, f"селектор найденной кнопки запомнен: {sel}")
        tail = "Селектор записан — следующие телефоны найдут цель без нейросети."
    else:
        tail = ("Под точкой нет подходящего узла (игра или рисованный экран) — "
                "запомнен только факт, селектор не построен.")
    _record(ctx, dv.VLM_ASSIST, "нейросеть помогла найти цель; запомнено",
            f"{what.get('label') or '; '.join(goal_texts(what))[:80]}. {tail}",
            f"assist|{k or '; '.join(goal_texts(what))[:80]}")
