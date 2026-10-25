"""Отчёт о запуске: одна самодостаточная HTML-страница.

Чистый модуль: на входе report.json и байты кадров, на выходе строка. Без
сети, без диска и без шаблонизатора (jinja2 в requirements нет) — страницу
пересылают по почте/мессенджеру, поэтому стили inline, кадры base64 внутри,
ни одной внешней ссылки. Весь текст из отчёта экранируется: в нём бывают
сообщения с экрана телефона и имена из сценариев.
"""
from __future__ import annotations

import base64
import html
import io

STATUS_RU = {"ok": "ок", "retried": "с повтором", "blind": "вслепую",
             "skipped": "пропущен", "failed": "упал"}
JOB_STATUS_RU = {"passed": "прошёл", "failed": "упал", "cancelled": "отменён",
                 "running": "идёт", "queued": "в очереди", "held": "ждёт решения",
                 "cancelling": "отменяется"}
LAYER_RU = {"selector": "по селектору", "tree-text": "по тексту в дереве экрана",
            "ocr": "по распознанному тексту", "template": "по картинке",
            "point": "по координатам (вслепую)"}
# Цвет статуса — не единственный признак: слово рядом всегда есть.
_COLOR = {"ok": "#1a7f37", "retried": "#9a6700", "blind": "#bc4c00",
          "skipped": "#6e7781", "failed": "#cf222e"}
THUMB_WIDTH = 270

_CSS = """
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:16px;
background:#f6f8fa;color:#1f2328}
main{max-width:960px;margin:0 auto}
h1{font-size:22px;margin:0 0 8px}
.card{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:12px 16px;margin:12px 0}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px 16px}
.sum b{display:block;font-size:12px;color:#656d76;font-weight:600}
.step{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}
.step img{width:135px;border:1px solid #d0d7de;border-radius:6px}
.badge{font-weight:700}
.muted{color:#656d76;font-size:13px}
.err{border-color:#cf222e;background:#fff5f5}
table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid #d0d7de;padding:6px 8px;text-align:left}
"""


def _e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def thumb(data: bytes, width: int = THUMB_WIDTH) -> bytes:
    """Уменьшить кадр до превью: страница с 40 полноразмерными PNG весила бы
    десятки мегабайт. Не получилось (нет Pillow, битый файл) — как есть."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.width <= width:
            return data
        im = im.convert("RGB")
        im = im.resize((width, max(1, round(im.height * width / im.width))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=60)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return data


def _img(data: bytes | None, alt: str) -> str:
    if not data:
        return ""
    data = thumb(data)
    mime = "image/jpeg" if data[:2] == b"\xff\xd8" else "image/png"
    return (f'<img alt="{_e(alt)}" src="data:{mime};base64,'
            f'{base64.b64encode(data).decode("ascii")}">')


def _secs(v) -> str:
    try:
        return f"{float(v):.1f} с".replace(".", ",")
    except (TypeError, ValueError):
        return "—"


def _version(v) -> str:
    if isinstance(v, str) and v.strip():
        return v.strip()
    if not isinstance(v, dict):
        return "не определена"
    name = v.get("name") or ""
    code = v.get("code")
    out = name or "?"
    if code:
        out += f" (код {code})"
    if v.get("package"):
        out = f"{v['package']} {out}"
    return out


def fallback_count(steps: list) -> int:
    return sum(1 for s in steps if s.get("degraded"))


# Ключи причин — для кода, человеку они ничего не говорят.
REASON_RU = {"settle": "ждали, пока экран устоится", "wait_target": "ждали, пока цель замрёт",
             "sleep": "паузы сценария", "resolve": "поиск цели", "other": "прочее"}


def _time_by_reason(tbr) -> str:
    if not tbr:
        return ""
    items = tbr.items() if isinstance(tbr, dict) else tbr
    rows = []
    for it in items:
        k, v = it if isinstance(it, (tuple, list)) else (it, "")
        rows.append(f"<li>{_e(REASON_RU.get(k, k))}: {_e(_secs(v))}</li>")
    return ('<div><b>Время по причинам</b><ul style="margin:0;padding-left:18px">'
            + "".join(rows) + "</ul></div>")


def _layer_text(s: dict) -> str:
    layer = s.get("layer")
    if not layer:
        return ""
    txt = LAYER_RU.get(layer, layer)
    if s.get("detail"):
        txt += f" — {s['detail']}"
    return txt


def render_html(report: dict, shots: dict[str, bytes]) -> str:
    steps = report.get("steps") or []
    status = report.get("status") or ""
    fb = fallback_count(steps)
    info = report.get("error_info") or {}
    parts = [
        f'<h1>Отчёт о запуске: {_e(report.get("scenario"))}</h1>',
        '<div class="card sum">',
        f'<div><b>Итог</b><span class="badge" style="color:'
        f'{"#1a7f37" if status == "passed" else "#cf222e"}">'
        f'{_e(JOB_STATUS_RU.get(status, status))}</span></div>',
        f'<div><b>Телефон</b>{_e(report.get("device") or report.get("serial"))}</div>',
        f'<div><b>Сценарий</b>{_e(report.get("scenario"))}</div>',
        f'<div><b>Версия приложения</b>{_e(_version(report.get("app_version")))}</div>',
        f'<div><b>Найдено запасным способом</b>{fb} из {len(steps)} шагов</div>',
        _time_by_reason(report.get("time_by_reason")),
        '</div>',
    ]
    if report.get("error"):
        parts.append(
            '<div class="card err"><b>Почему упал</b><br>'
            f'{_e(info.get("title") or report["error"])}'
            + (f'<br><span class="muted">{_e(info["hint"])}</span>' if info.get("hint") else "")
            + f'<br><span class="muted">{_e(report["error"])}</span></div>')
    for s in steps:
        st = s.get("status") or "ok"
        layer = _layer_text(s)
        meta = [f'проходов: {_e(s.get("n", 1))}', _e(_secs(s.get("secs")))]
        shot = _img(shots.get(s.get("shot") or ""), f'Кадр шага {s.get("i", 0) + 1}')
        exp = _img(shots.get(s.get("expected") or ""), "Что ожидали увидеть")
        warn = (' <span class="badge" style="color:#9a6700">запасной способ</span>'
                if s.get("degraded") else "")
        parts.append(
            '<div class="card step"><div style="flex:1;min-width:220px">'
            f'<b>Шаг {_e(s.get("i", 0) + 1)}.</b> {_e(s.get("label"))}<br>'
            f'<span class="badge" style="color:{_COLOR.get(st, "#1f2328")}">'
            f'{_e(STATUS_RU.get(st, st))}</span> · '
            f'<span class="muted">{" · ".join(meta)}</span>'
            + (f'<br><span class="muted">Цель найдена: {_e(layer)}</span>{warn}' if layer else "")
            + f'</div>{shot}{exp}</div>')
    if not steps:
        parts.append('<div class="card muted">Шаги не записывались.</div>')
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Отчёт: {_e(report.get("scenario"))}</title>'
            f'<style>{_CSS}</style></head><body><main>{"".join(parts)}</main></body></html>')


def render_batch_html(rows: list[dict], link) -> str:
    """Сводка пачки. rows: {id, device, scenario, status, error, fallback};
    link(id) -> адрес отчёта этого телефона."""
    passed = sum(1 for r in rows if r.get("status") == "passed")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    fb = sum(1 for r in rows if r.get("fallback"))
    body = []
    for r in rows:
        st = r.get("status") or ""
        color = "#1a7f37" if st == "passed" else "#cf222e" if st == "failed" else "#6e7781"
        fbt = f'запасной способ: {_e(r["fallback"])} шаг.' if r.get("fallback") else ""
        body.append(
            f'<tr><td>{_e(r.get("device"))}</td>'
            f'<td><span class="badge" style="color:{color}">{_e(JOB_STATUS_RU.get(st, st))}</span></td>'
            f'<td class="muted">{_e(r.get("error") or fbt)}</td>'
            f'<td><a href="{_e(link(r.get("id")))}">Отчёт</a></td></tr>')
    name = rows[0].get("scenario") if rows else ""
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Отчёт по пачке</title><style>{_CSS}</style></head><body><main>'
            f'<h1>Отчёт по пачке: {_e(name)}</h1>'
            f'<div class="card sum"><div><b>Прошло</b>{passed}</div>'
            f'<div><b>Упало</b>{failed}</div>'
            f'<div><b>Доехало запасным способом</b>{fb}</div>'
            f'<div><b>Всего телефонов</b>{len(rows)}</div></div>'
            '<div class="card"><table><tr><th>Телефон</th><th>Результат</th>'
            f'<th>Примечание</th><th></th></tr>{"".join(body)}</table></div>'
            '</main></body></html>')
