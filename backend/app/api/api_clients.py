from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import add_audit
from app.core.auth import (
    ALL_SCOPES,
    Actor,
    create_api_client_token,
    generate_token,
    hash_token,
    require_web_admin,
    token_prefix,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError, not_found
from app.core.responses import envelope
from app.models import ApiClient, ApiClientScope, ApiClientToken
from app.schemas import ApiClientCreateRequest, ApiClientUpdateRequest
from app.services.domain import parse_utc, utc_text

router = APIRouter(prefix="/api/v1/api-clients", tags=["api-clients"])


def _request_id(request: Request) -> str:
    return request.state.request_id


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _get(db: Session, client_id: int) -> ApiClient:
    client = db.get(ApiClient, client_id)
    if client is None:
        raise not_found("api_client")
    return client


def _serialize(db: Session, c: ApiClient) -> dict:
    scopes = db.scalars(
        select(ApiClientScope.scope).where(ApiClientScope.api_client_id == c.id)
    ).all()
    tokens = db.scalars(
        select(ApiClientToken)
        .where(ApiClientToken.api_client_id == c.id)
        .order_by(ApiClientToken.id)
    ).all()
    now = datetime.now(UTC)
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "skill_name": c.skill_name,
        "skill_version": c.skill_version,
        "status": c.status,
        "scopes": sorted(scopes),
        "tokens": [
            {
                "id": t.id,
                "prefix": t.token_prefix,
                "state": (
                    "revoked"
                    if t.revoked_at is not None
                    else ("expired" if parse_utc(t.expires_at) <= now else "active")
                ),
                "expires_at": t.expires_at,
                "last_used_at": t.last_used_at,
            }
            for t in tokens
        ],
        "created_at": c.created_at,
    }


@router.get("")
def list_clients(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_web_admin)],
):
    clients = db.scalars(select(ApiClient).order_by(ApiClient.id.desc())).all()
    return envelope(request, [_serialize(db, c) for c in clients])


@router.post("", status_code=201)
def create_client(
    request: Request,
    payload: ApiClientCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_web_admin)],
):
    # create_api_client_token() validates scopes against ALL_SCOPES, creates the
    # client + scopes + token, writes its own "system" audit row, and commits.
    # It raises ValueError on unknown scopes — surface that as a clean 422
    # instead of letting it become a 500.
    unknown = set(payload.scopes) - ALL_SCOPES
    if unknown:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "包含未知的授权范围",
            [{"field": "scopes", "unknown": sorted(unknown)}],
        )
    client, _token, raw = create_api_client_token(
        db,
        name=payload.name,
        skill_name=payload.skill_name,
        skill_version=payload.skill_version,
        scopes=payload.scopes,
        expires_days=payload.expires_days,
        description=payload.description,
    )
    data = _serialize(db, client)
    data["token"] = raw  # plaintext token, surfaced only in this response
    return envelope(request, data, status_code=201)


@router.post("/{client_id}/tokens")
def rotate_token(
    request: Request,
    client_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    _get(db, client_id)  # raises 404 if missing
    now = datetime.now(UTC)
    # revoke all currently-active tokens immediately
    for t in db.scalars(
        select(ApiClientToken).where(
            ApiClientToken.api_client_id == client_id,
            ApiClientToken.revoked_at.is_(None),
        )
    ):
        t.revoked_at = utc_text(now)
    db.flush()
    raw_token = generate_token()
    db.add(
        ApiClientToken(
            api_client_id=client_id,
            token_prefix=token_prefix(raw_token),
            token_hash=hash_token(raw_token, get_settings()),
            created_at=utc_text(now),
            expires_at=utc_text(now + timedelta(days=365)),
        )
    )
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="api_client.rotate_token",
        outcome="success",
        http_status=200,
        target_type="api_client",
        target_id=client_id,
    )
    _commit(db)
    return envelope(request, {"token": raw_token})


@router.patch("/{client_id}")
def update_client(
    request: Request,
    client_id: int,
    payload: ApiClientUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    client = _get(db, client_id)
    if payload.status is not None:
        client.status = payload.status
    if payload.description is not None:
        client.description = payload.description
    if payload.scopes is not None:
        unknown = set(payload.scopes) - ALL_SCOPES
        if unknown:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "包含未知的授权范围",
                [{"field": "scopes", "unknown": sorted(unknown)}],
            )
        db.query(ApiClientScope).filter(
            ApiClientScope.api_client_id == client_id
        ).delete()
        for sc in sorted(set(payload.scopes)):
            db.add(ApiClientScope(api_client_id=client_id, scope=sc))
        client.scope_version = (client.scope_version or 0) + 1
    client.updated_at = utc_text()
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="api_client.update",
        outcome="success",
        http_status=200,
        target_type="api_client",
        target_id=client_id,
        metadata={"status": payload.status, "scopes": payload.scopes},
    )
    _commit(db)
    return envelope(request, _serialize(db, client))


@router.delete("/{client_id}", status_code=204)
def disable_client(
    request: Request,
    client_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    client = _get(db, client_id)
    client.status = "disabled"
    client.updated_at = utc_text()
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="api_client.disable",
        outcome="success",
        http_status=204,
        target_type="api_client",
        target_id=client_id,
    )
    _commit(db)
    return Response(status_code=204)


@router.delete("/{client_id}/permanent", status_code=204)
def delete_client_permanently(
    request: Request,
    client_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    client = _get(db, client_id)
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="api_client.delete",
        outcome="success",
        http_status=204,
        target_type="api_client",
        target_id=client_id,
        metadata={"name": client.name, "skill_name": client.skill_name},
    )
    db.delete(client)
    _commit(db)
    return Response(status_code=204)


@router.delete("/{client_id}/tokens/{token_id}", status_code=204)
def revoke_token(
    request: Request,
    client_id: int,
    token_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_web_admin)],
):
    _get(db, client_id)
    t = db.get(ApiClientToken, token_id)
    if t is None or t.api_client_id != client_id:
        raise not_found("api_token")
    t.revoked_at = utc_text()
    add_audit(
        db,
        request_id=_request_id(request),
        actor=actor,
        action="api_token.revoke",
        outcome="success",
        http_status=204,
        target_type="api_token",
        target_id=token_id,
    )
    _commit(db)
    return Response(status_code=204)
