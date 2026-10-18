"""Аккаунты: список, правка, импорт пачкой, раздача по телефонам."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from .. import accounts
from ..devices import registry

router = APIRouter(prefix="/api/accounts")


def _public(item: dict) -> dict:
    """Без пароля: список читается целиком и висит в DOM таблицы. Пароль
    отдаётся по одному — по явному «показать»."""
    out = {k: v for k, v in item.items() if k != "password"}
    out["has_password"] = bool(item.get("password"))
    return out


@router.get("")
def list_accounts():
    return [_public(a) for a in accounts.all_accounts()]


@router.get("/{account_id}/password")
def account_password(account_id: str):
    item = accounts.get(account_id)
    if item is None:
        raise HTTPException(404, "аккаунт не найден")
    # no-store: пароль не должен оседать в дисковом кэше браузера
    return JSONResponse({"password": item.get("password", "")},
                        headers={"Cache-Control": "no-store"})


@router.post("")
def create_account(payload: dict = Body(...)):
    if not str(payload.get("login") or "").strip():
        raise HTTPException(400, "нужен логин")
    try:
        return _public(accounts.create(payload))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/import")
def import_accounts(text: str = Body(...), platform: str = Body(...)):
    if not platform.strip():
        raise HTTPException(400, "укажите платформу")
    try:
        report = accounts.import_report(text, platform.strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "count": len(report["created"]),
            "duplicates": report["duplicates"], "bad_lines": report["bad_lines"]}


@router.post("/autobind")
def autobind(platform: str = Body(...), serials: list[str] | None = Body(None)):
    """Без serials — раздаём всем телефонам фермы."""
    serials = serials or [d.serial for d in registry.all()]
    return {"ok": True, "count": accounts.auto_bind(platform, serials)}


@router.patch("/{account_id}")
def update_account(account_id: str, payload: dict = Body(...)):
    try:
        item = accounts.update(account_id, payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if item is None:
        raise HTTPException(404, "аккаунт не найден")
    return _public(item)


@router.delete("/{account_id}")
def delete_account(account_id: str):
    if not accounts.delete(account_id):
        raise HTTPException(404, "аккаунт не найден")
    return {"ok": True}
