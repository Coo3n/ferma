"""Отклонения от сценария: список, «прочитано», удаление.

Порядок объявления маршрутов значим: `/seen` и `/clear` стоят до
`/{item_id}`-шаблонов того же метода, иначе попадут в них как идентификатор
(та же причина, что в jobs.py).
"""
from __future__ import annotations

import base64
import json
from urllib.parse import quote
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import config
from .. import ui as uitree
from ..deviations import FAIL, deviations

router = APIRouter(prefix="/api/deviations")


@router.get("")
def list_deviations(limit: int = 60, unseen: bool = False):
    return {"deviations": deviations.list(limit=limit, unseen_only=unseen),
            "unseen": deviations.unseen()}


@router.post("/seen")
def mark_all_seen():
    return {"ok": True, "marked": deviations.mark_seen()}


@router.post("/clear")
def clear_deviations():
    return {"ok": True, "removed": deviations.clear()}


@router.post("/{item_id}/seen")
def mark_seen(item_id: str):
    return {"ok": True, "marked": deviations.mark_seen(item_id)}


@router.delete("/{item_id}")
def delete_deviation(item_id: str):
    if not deviations.delete(item_id):
        raise HTTPException(404, "отклонение не найдено")
    return {"ok": True}


def _артефакт(item, name: str) -> Path | None:
    """Файл артефакта задачи или None. Имена из журнала не доверяем: та же
    защита от выхода за корень, что у `/api/jobs/{id}/artifacts/{name}`."""
    if not item.job_id or not name or name != Path(name).name:
        return None  # только голое имя файла: без разделителей и ..
    root = Path(config.ARTIFACTS_DIR).resolve()
    job_dir = (root / item.job_id).resolve()
    path = (job_dir / name).resolve()
    # Внутри каталога именно этой задачи, а не просто под корнем артефактов.
    return path if job_dir.parent == root and job_dir in path.parents \
        and path.is_file() else None


def _найти(item_id: str):
    item = deviations.get(item_id)
    if item is None:
        raise HTTPException(404, "отклонение не найдено")
    return item


@router.get("/{item_id}/shot")
def deviation_shot(item_id: str):
    """Метаданные кадра: сам JPEG клиент берёт по `url` (ему нужен кеш браузера)."""
    item = _найти(item_id)
    if not item.shot:
        raise HTTPException(404, "у этого отклонения нет снимка экрана")
    if _артефакт(item, item.shot) is None:
        raise HTTPException(404, f"файл {item.shot} удалён или недоступен")
    try:
        miss = json.loads(item.miss) if item.miss else {}
    except ValueError:
        miss = {}
    if not isinstance(miss, dict):
        miss = {}
    return {
        "url": (f"/api/jobs/{quote(item.job_id, safe='')}"
                f"/artifacts/{quote(item.shot, safe='')}"),
        "alt": f"Снимок экрана «{', '.join(item.devices) or 'устройство'}», "
               f"сценарий «{item.scenario_name or item.scenario_key}»",
        "miss": miss,
        "step_index": item.step_index,
        "job_id": item.job_id,
        "shot": item.shot,
        "kind": item.kind,
    }


@router.get("/{item_id}/dump")
def deviation_dump(item_id: str):
    """Дамп для починки шага: как `/inspect`, но из артефактов упавшей задачи."""
    item = _найти(item_id)
    xml_path = _артефакт(item, "failure_hierarchy.xml")
    if xml_path is None:
        raise HTTPException(404, "UI-дерево этого падения не сохранено"
                            if item.kind == FAIL else
                            "у этого отклонения нет сохранённого UI-дерева")
    jpg = _артефакт(item, "99_failure.jpg")
    if jpg is None:
        raise HTTPException(404, "снимок падения удалён или недоступен")
    size = _артефакт(item, "failure_size.json")
    try:
        data = json.loads(size.read_text("utf-8")) if size else {}
        width, height = int(data["width"]), int(data["height"])
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(404, "размер экрана не сохранён")
    # Файл мог пропасть между проверкой и чтением: 404, а не необработанное 500.
    try:
        nodes = uitree.parse(xml_path.read_text("utf-8"), width, height)
        shot = base64.b64encode(jpg.read_bytes()).decode("ascii")
    except uitree.InspectError as e:
        raise HTTPException(500, str(e))
    except UnicodeError:
        raise HTTPException(500, "UI-дерево повреждено: не читается как UTF-8")
    except OSError:
        raise HTTPException(404, "артефакт пропал или недоступен")
    return {
        "width": width,
        "height": height,
        "screenshot": "data:image/jpeg;base64," + shot,
        "nodes": uitree.to_payload(nodes),
    }
