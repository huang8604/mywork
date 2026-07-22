from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    Actor,
    _check_rate_limit,
    get_actor,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.responses import envelope
from app.models import WebCredential
from app.models.entities import utc_now_text
from app.schemas import LoginRequest, PasswordChangeRequest

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _find_credential(db: Session, username: str) -> WebCredential | None:
    return db.scalar(select(WebCredential).where(WebCredential.username == username))


@router.post("/login")
def login(
    request: Request,
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
):
    settings = get_settings()
    _check_rate_limit(request, f"login:{payload.username}", settings)
    cred = _find_credential(db, payload.username)
    if (
        cred is None
        or cred.disabled_at is not None
        or not verify_password(cred.password_hash, payload.password)
    ):
        raise AppError(401, "AUTH_REQUIRED", "用户名或密码错误")
    request.session.clear()
    request.session["sub"] = cred.username
    return envelope(
        request,
        {"username": cred.username, "role": cred.role, "actor_type": "web_user"},
    )


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return envelope(request, {"ok": True})


@router.get("/me")
def me(
    request: Request,
    actor: Annotated[Actor, Depends(get_actor)],
):
    return envelope(
        request,
        {
            "username": actor.actor_id if actor.actor_type == "web_user" else None,
            "role": actor.role,
            "actor_type": actor.actor_type,
        },
    )


@router.post("/password")
def change_password(
    request: Request,
    payload: PasswordChangeRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(get_actor)],
):
    if actor.actor_type != "web_user" or actor.role is None:
        raise AppError(403, "FORBIDDEN", "仅 Web 登录用户可修改口令")
    cred = _find_credential(db, actor.actor_id)
    if cred is None or not verify_password(cred.password_hash, payload.old_password):
        raise AppError(401, "AUTH_REQUIRED", "原口令不正确")
    cred.password_hash = hash_password(payload.new_password)
    cred.updated_at = utc_now_text()
    db.commit()
    return envelope(request, {"ok": True})
