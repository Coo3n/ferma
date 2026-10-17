"""Журнал задач и артефакты.

Порядок объявления маршрутов значим: `/cancel_all` и `/clear` должны стоять
до `/{job_id}`-шаблонов того же метода, иначе попадут в них как идентификатор.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, Response

from .. import config
import json
from ..devices.runner import runner

router = APIRouter(prefix="/api/jobs")


@router.get("")
def list_jobs(limit: int = 60, serial: Optional[str] = None, batch: Optional[str] = None):
    return runner.list_jobs(limit=limit, serial=serial, batch=batch)


@router.post("/cancel_all")
def cancel_all(serial: Optional[str] = None):
    return {"ok": True, "cancelled": runner.cancel_all(serial)}


@router.post("/clear")
def clear_finished(serial: Optional[str] = None):
    """Убрать завершённые задачи из журнала. Артефакты на диске остаются."""
    return {"ok": True, "removed": runner.clear_finished(serial)}


_CSV_STATUS = {
    "queued": "в очереди", "running": "идёт", "held": "ждёт решения",
    "cancelling": "отменяется", "passed": "прошёл", "failed": "упал",
    "cancelled": "отменён",
}


def jobs_csv(jobs: list[dict]) -> str:
    """CSV журнала запусков для Excel.

    Разделитель «;» и десятичная запятая — так русский Excel сам разложит
    колонки и поймёт длительность как число. BOM в начале — иначе Excel
    читает файл как cp1251 и кириллица превращается в кракозябры.
    """
    import csv
    import io
    import time as _time

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["время начала", "сценарий", "телефон", "статус", "длительность (с)", "ошибка"])
    for j in jobs:
        ts = j.get("started_at") or j.get("created_at")
        started = _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(ts)) if ts else ""
        dur = f"{j.get('duration') or 0:.1f}".replace(".", ",") if j.get("started_at") else ""
        err = " ".join(str(j.get("error") or "").split())
        w.writerow([started, j.get("scenario_name") or j.get("scenario_key") or "",
                    j.get("device_name") or j.get("serial") or "",
                    _CSV_STATUS.get(j.get("status"), j.get("status") or ""), dur, err])
    return "\ufeff" + buf.getvalue()


# Объявлен до /{job_id}: иначе «export.csv» уйдёт в get_job как id задачи.
@router.get("/export.csv")
def export_csv():
    import datetime
    name = f"farm-jobs-{datetime.date.today():%Y-%m-%d}.csv"
    return Response(jobs_csv(runner.list_jobs(limit=10 ** 9)).encode("utf-8"),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{job_id}")
def get_job(job_id: str):
    job = runner.get(job_id)
    if job is None:
        raise HTTPException(404, "задача не найдена")
    return job.to_dict(with_log=True)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    return {"ok": runner.cancel(job_id)}


@router.post("/{job_id}/decide")
def decide_job(job_id: str, payload: dict = Body(...)):
    """Ответ человека остановленной задаче: повторить шаг, пропустить, уронить.

    409, а не 404, когда задача уже не ждёт: ответ опоздал — за это время
    истёк HOLD_TIMEOUT или кто-то ответил раньше. Разница важна, потому что
    молчаливое «ок» означало бы, что решение применилось, а оно нет.

    К «повторить» можно приложить `target` — исправленную цель click_target.
    """
    try:
        ok = runner.decide(job_id, payload.get("decision"),
                          payload.get("target"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(409, "задача больше не ждёт решения")
    return {"ok": True}


@router.delete("/{job_id}")
def delete_job(job_id: str):
    if not runner.delete(job_id):
        raise HTTPException(409, "задача выполняется или не найдена — сначала отмените её")
    return {"ok": True}


@router.get("/{job_id}/artifacts/{name}")
def artifact(job_id: str, name: str):
    path = (Path(config.ARTIFACTS_DIR) / job_id / name).resolve()
    root = Path(config.ARTIFACTS_DIR).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, "артефакт не найден")
    # Внутри — текст с экрана телефона (UI-дерево, logcat). Открытый в
    # новой вкладке, он не должен исполняться как страница фермы.
    return FileResponse(path, headers={"Content-Security-Policy": "sandbox",
                                       "X-Content-Type-Options": "nosniff"})


# Слепков у задачи может быть несколько: один от падения и по одному на каждый
# незнакомый экран, обойдённый вслепую. Имя приходит из интерфейса, поэтому
# закрыто регуляркой, а не только проверкой пути.
OBSTACLE_RE = re.compile(r"^obstacle(_(escaped|lost)_\d{2})?\.json$")

# Идентификатор задачи — uuid4().hex[:12] (см. devices/runner.py). Проверяем
# формат, потому что job_id подставляется в путь к артефактам. Раньше от
# обхода каталога защищал сам поиск задачи в журнале: неизвестный id просто
# не находился. Журнал задачу забывает, а слепок на диске остаётся, поэтому
# поиск перестал быть обязательным — и защиту пути нужно держать явно.
JOB_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")


@router.get("/{job_id}/obstacle")
def job_obstacle(job_id: str, name: str = "obstacle.json"):
    """Слепок преграды: чем её опознать и что было на экране.

    Отдельным запросом, а не в теле задачи: нужен только в момент обучения,
    а задач в журнале сотни.

    Задача в журнале не обязательна. Список непокрытых преград строится по
    файлам в artifacts/, а журнал держит только последние задачи — старая
    преграда оставалась видимой, но «научить» по ней падало с «задача не
    найдена», хотя слепок лежал на диске. Из задачи берутся лишь serial и
    error, и без них обучение работает: чем опознать экран, написано в
    самом слепке.
    """
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(400, "недопустимый идентификатор задачи")
    if not OBSTACLE_RE.match(name):
        raise HTTPException(400, f"недопустимое имя слепка «{name}»")
    path = Path(config.ARTIFACTS_DIR) / job_id / name
    if not path.is_file():
        raise HTTPException(404, "слепок преграды не снимался")
    try:
        слепок = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"слепок не читается: {e}")
    job = runner.get(job_id)
    слепок["serial"] = job.serial if job else None
    слепок["error"] = job.error if job else None
    return слепок
