"""Разбор прогона: по отчёту (и по скриншотам только при vision == yes)."""
from __future__ import annotations

import json

from . import client, review, settings

BASIS_OBS = ("confirmed", "probable", "unverified")
MAX_SHOTS = 3


_ST = {"ok": "выполнен", "retried": "выполнен с повтором", "blind": "выполнен без проверки результата",
       "skipped": "пропущен", "failed": "не выполнен"}


def facts(timeline: list, status: str, error: str, total: int) -> list:
    """Подтверждённые наблюдения прямо из данных запуска: их не пишет нейросеть."""
    out = []
    for t in timeline or []:
        if not isinstance(t, dict) or t.get("i") is None:
            continue
        st = _ST.get(t.get("status"))
        if st:
            out.append({"text": f"Шаг {int(t['i']) + 1} «{str(t.get('label') or '')[:60]}» {st}.", "basis": "confirmed"})
    if status == "held":
        n = len(timeline or [])
        out.append({"text": f"Запуск остановился на шаге {n} из {total}: ферма не смогла выполнить его сама "
                            "и ждёт решения человека.", "basis": "confirmed"})
    elif status in ("failed", "error") and error:
        out.append({"text": f"Запуск завершился ошибкой: {error[:200]}", "basis": "confirmed"})
    return out


def _useful(text: str) -> bool:
    return len(text.strip()) >= 8 and sum(ch.isalpha() for ch in text) >= 5


def run(steps: list, report: dict, shots: dict, job_error: str, timeline: list | None = None,
        status: str = "") -> dict:
    cfg = settings.get()
    rep_steps = [{k: s.get(k) for k in ("i", "label", "status", "secs", "n")}
                 for s in (report.get("steps") or [])][:80]
    use_images = cfg.vision == "yes" and bool(shots)
    note = None
    if cfg.vision != "yes":
        note = ("Скриншоты не анализировались: модель не подтверждена как видящая картинки "
                "(проверьте её в настройках ИИ). Выводы — только по журналу шагов.")
    elif not shots:
        note = "В запуске нет скриншотов — выводы только по журналу шагов."
    prompt = ("Analyze the result of an Android automation run. Answer ONLY with JSON "
              '{"observations":[{"text":"..","basis":"confirmed|probable|unverified"}],'
              '"suggestions":[Finding,...]}. confirmed = directly visible in the log/screenshots. '
              + review.FINDING_SPEC + "\nSteps:\n" + review.numbered(steps)
              + "\nRun log: " + json.dumps(rep_steps, ensure_ascii=False)
              + "\nError: " + (job_error or "none"))
    images = list(shots.values())[-MAX_SHOTS:] if use_images else None
    try:
        reply = client.chat([{"role": "user", "content": prompt}], images=images, max_tokens=2000)
    except client.VlmError as e:
        raise review.ModelReplyError(f"нейросеть не ответила: {e}")
    data = review.parse_json(reply)
    if not isinstance(data, dict):
        raise review.ModelReplyError("ответ модели не в ожидаемом формате")
    obs = facts(timeline or [], status, job_error, len(steps))
    for o in data.get("observations") or []:
        if isinstance(o, dict) and isinstance(o.get("text"), str) and _useful(o["text"]):
            basis = o.get("basis") if o.get("basis") in BASIS_OBS else "unverified"
            if basis == "confirmed" and not use_images and not rep_steps:
                basis = "unverified"
            obs.append({"text": o["text"].strip()[:500], "basis": basis})
    sugg, dropped = review.validate_findings(data.get("suggestions") or [], steps)
    out = {"observations": obs, "suggestions": sugg, "vision_used": use_images, "dropped": dropped}
    if note:
        out["note"] = note
    return out
