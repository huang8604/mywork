from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import add_audit
from app.core.auth import Actor, hash_password, require_web_admin
from app.core.database import get_db
from app.core.errors import AppError, not_found
from app.core.responses import envelope
from app.models import WebCredential
from app.models.entities import utc_now_text
from app.schemas import UserCreateRequest, UserPasswordResetRequest, UserUpdateRequest

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _data(cred: WebCredential) -> dict[str, object]:
    return {
        "id": cred.id,
        "username": cred.username,
        "role": cred.role,
        "disabled_at": cred.disabled_at,
        "created_at": cred.created_at,
    }


def _get(db: Session, user_id: int) -> WebCredential:
    cred = db.get(WebCredential, user_id)
    if cred is None:
        raise not_found("user")
    return cred


def _active_admin_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(WebCredential)
            .where(WebCredential.role == "admin", WebCredential.disabled_at.is_(None))
        )
        or 0
    )


@router.get("")
def list_users(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_web_admin)],
):
    creds = db.scalars(select(WebCredential).order_by(WebCredential.id)).all()
    return envelope(request, [_data(cred) for cred in creds])


@router.post("", status_code=201)
def create_user(
    request: Request,
    payload: UserCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    cred = WebCredential(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(cred)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "DUPLICATE_USER", "用户名已存在")
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="user.create",
        outcome="success",
        http_status=201,
        target_type="web_user",
        target_id=cred.id,
        metadata={"role": cred.role},
    )
    _commit(db)
    return envelope(request, _data(cred), status_code=201)


@router.patch("/{user_id}")
def update_user(
    request: Request,
    user_id: int,
    payload: UserUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    cred = _get(db, user_id)
    if payload.role is not None and payload.role != cred.role:
        if (
            cred.role == "admin"
            and cred.disabled_at is None
            and _active_admin_count(db) <= 1
        ):
            raise AppError(409, "LAST_ADMIN", "不能降级最后一个管理员")
        cred.role = payload.role
    if payload.disabled is not None:
        is_disabled = cred.disabled_at is not None
        if payload.disabled and not is_disabled:
            if cred.username == actor.actor_id:
                raise AppError(409, "SELF_GUARD", "不能禁用当前登录的自己")
            if cred.role == "admin" and _active_admin_count(db) <= 1:
                raise AppError(409, "LAST_ADMIN", "不能禁用最后一个管理员")
            cred.disabled_at = utc_now_text()
        elif not payload.disabled and is_disabled:
            cred.disabled_at = None
    cred.updated_at = utc_now_text()
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="user.update",
        outcome="success",
        http_status=200,
        target_type="web_user",
        target_id=cred.id,
        metadata={"role": payload.role, "disabled": payload.disabled},
    )
    _commit(db)
    return envelope(request, _data(cred))


@router.post("/{user_id}/password")
def reset_password(
    request: Request,
    user_id: int,
    payload: UserPasswordResetRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    cred = _get(db, user_id)
    cred.password_hash = hash_password(payload.new_password)
    cred.updated_at = utc_now_text()
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="user.password_reset",
        outcome="success",
        http_status=200,
        target_type="web_user",
        target_id=cred.id,
    )
    _commit(db)
    return envelope(request, {"ok": True})


@router.delete("/{user_id}", status_code=204)
def delete_user(
    request: Request,
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    cred = _get(db, user_id)
    if cred.username == actor.actor_id:
        raise AppError(409, "SELF_GUARD", "不能删除当前登录的自己")
    if cred.role == "admin" and _active_admin_count(db) <= 1:
        raise AppError(409, "LAST_ADMIN", "不能删除最后一个管理员")
    db.delete(cred)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="user.delete",
        outcome="success",
        http_status=204,
        target_type="web_user",
        target_id=user_id,
    )
    _commit(db)
    return Response(status_code=204)
