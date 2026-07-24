from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.core.audit import add_audit
from app.core.auth import Actor, require_scopes
from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import AppError, not_found
from app.core.responses import envelope
from app.models import PracticeReviewRound, PracticeSession, PracticeSessionItem, Word
from app.schemas import BatchResults, RoundCreate, RoundResult, SessionUpdate, StrategyRequest, VersionRequest
from app.services.domain import utc_text
from app.services.idempotency import claim, complete
from app.services.recitation import build_recitation_md, render_recitation_pdf
from app.services.sessions import auto_archive_expired_sessions, delete_session, update_session
from app.services.reviews import batch_round_results, put_round_result
from app.services.serializers import review_data, round_data, session_data
from app.services.strategy import generate_session
from app.services.words import word_audio_file

router = APIRouter(prefix="/api/v1", tags=["practice"])
logger = logging.getLogger("word_memory.practice")


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _idem_response(request: Request, idem):
    return envelope(
        request,
        idem.replay_data,
        status_code=idem.replay_status,
        headers={"Idempotency-Replayed": "true"},
    )


@router.post("/daily-table/generate")
def generate(
    request: Request,
    payload: StrategyRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("practice:generate"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/daily-table/generate",
        key=idempotency_key,
        payload=payload.model_dump(mode="json"),
        required=True,
    )
    if idem and idem.replayed:
        return _idem_response(request, idem)
    skill = (
        (actor.skill_name or "unknown", actor.skill_version or "unknown")
        if actor.actor_type == "api_client"
        else None
    )
    session = generate_session(db, payload, actor, skill)
    data = session_data(db, session, include_items=True)
    base = get_settings().public_base_url
    data["web_url"] = f"{base}/daily/sessions/{session.id}"
    data["print_url"] = f"{base}/daily/sessions/{session.id}?view=print"
    complete(idem, data=data, status_code=201, resource_type="practice_session", resource_id=session.id)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="practice.generate",
        outcome="success",
        http_status=201,
        target_type="practice_session",
        target_id=session.id,
    )
    _commit(db)
    return envelope(request, data, status_code=201)


@router.get("/practice-sessions")
def list_sessions(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("practice:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: str | None = None,
    created_by_actor_type: str | None = None,
    generated_from: str | None = None,
    generated_to: str | None = None,
):
    if status and status not in {"active", "archived"}:
        raise AppError(422, "VALIDATION_ERROR", "无效的复习表状态")
    if created_by_actor_type and created_by_actor_type not in {"web_user", "api_client"}:
        raise AppError(422, "VALIDATION_ERROR", "无效的来源类型")
    archived_count = auto_archive_expired_sessions(db)
    if archived_count:
        _commit(db)
        logger.info("auto_archived_practice_sessions count=%s age_days=15", archived_count)

    # Legacy versions could persist a zero-item session. Keep those records out
    # of every list while preserving direct access for diagnostics.
    filters = [
        PracticeSession.id.in_(select(PracticeSessionItem.session_id).distinct())
    ]
    for column, value in (
        (PracticeSession.status, status or "active"),
        (PracticeSession.created_by_actor_type, created_by_actor_type),
    ):
        if value is not None:
            filters.append(column == value)
    if generated_from:
        filters.append(PracticeSession.generated_at >= generated_from)
    if generated_to:
        filters.append(PracticeSession.generated_at <= generated_to)
    total = db.scalar(
        select(func.count()).select_from(PracticeSession).where(and_(*filters))
    ) or 0
    sessions = db.scalars(
        select(PracticeSession)
        .where(and_(*filters))
        .order_by(desc(PracticeSession.generated_at), desc(PracticeSession.id))
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return envelope(
        request,
        [session_data(db, item, include_items=False) for item in sessions],
        meta={"page": page, "size": size, "total": total},
    )


def _session(db: Session, session_id: int) -> PracticeSession:
    session = db.get(PracticeSession, session_id)
    if session is None:
        raise not_found("practice session")
    return session


@router.get("/practice-sessions/{session_id}")
def get_session(
    request: Request,
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("practice:read"))],
):
    return envelope(request, session_data(db, _session(db, session_id), include_items=True))


@router.get("/practice-sessions/{session_id}/items/{item_id}/audio")
def get_session_item_audio(
    session_id: int,
    item_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("practice:read"))],
):
    _session(db, session_id)
    item = db.scalar(
        select(PracticeSessionItem).where(
            PracticeSessionItem.session_id == session_id,
            PracticeSessionItem.id == item_id,
        )
    )
    if item is None:
        raise not_found("practice session item")
    word = db.get(Word, item.word_id)
    if word is None or word.deleted_at:
        raise not_found("word")
    audio = word_audio_file(word)
    if audio is None:
        raise AppError(404, "AUDIO_NOT_FOUND", "音频尚未生成")
    return FileResponse(
        audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline"},
    )


@router.post("/practice-sessions/{session_id}/printed")
def printed(
    request: Request,
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("practice:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/practice-sessions/{session_id}/printed",
        key=idempotency_key,
        payload={"session_id": session_id},
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return _idem_response(request, idem)
    session = _session(db, session_id)
    if session.printed_at is None:
        session.printed_at = utc_text()
        session.version += 1
    data = session_data(db, session, include_items=False)
    complete(idem, data=data, status_code=200, resource_type="practice_session", resource_id=session.id)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="practice.printed",
        outcome="success",
        http_status=200,
        target_type="practice_session",
        target_id=session.id,
    )
    _commit(db)
    return envelope(request, data)


@router.post("/practice-sessions/{session_id}/archive")
def archive(
    request: Request,
    session_id: int,
    payload: VersionRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("practice:write"))],
):
    session = _session(db, session_id)
    if session.version != payload.expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "复习表已被修改，请刷新后重试",
            [{"current_version": session.version}],
        )
    if session.status != "archived":
        session.status = "archived"
        session.archived_at = utc_text()
        session.version += 1
    data = session_data(db, session, include_items=False)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="practice.archive",
        outcome="success",
        http_status=200,
        target_type="practice_session",
        target_id=session.id,
    )
    _commit(db)
    return envelope(request, data)


@router.patch("/practice-sessions/{session_id}")
def update_session_route(
    request: Request,
    session_id: int,
    payload: SessionUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("practice:write"))],
):
    session = update_session(db, session_id, payload)
    data = session_data(db, session, include_items=False)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="practice.update",
        outcome="success",
        http_status=200,
        target_type="practice_session",
        target_id=session_id,
    )
    _commit(db)
    return envelope(request, data)


@router.delete("/practice-sessions/{session_id}", status_code=204)
def delete_session_route(
    request: Request,
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("practice:write"))],
    expected_version: Annotated[int, Query(gt=0)],
):
    delete_session(db, session_id, expected_version)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="practice.delete",
        outcome="success",
        http_status=204,
        target_type="practice_session",
        target_id=session_id,
    )
    _commit(db)
    return Response(status_code=204)


@router.get("/practice-sessions/{session_id}/recitation")
def recitation(
    request: Request,
    session_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("practice:read"))],
    format: str = "pdf",
):
    # Export a session as the 单词背诵表 handout: markdown (the canonical
    # template) or PDF rendered from a themed HTML template via weasyprint.
    session = _session(db, session_id)
    if format not in {"pdf", "md"}:
        raise AppError(422, "VALIDATION_ERROR", "format 必须是 pdf 或 md")
    items = list(
        db.scalars(
            select(PracticeSessionItem)
            .where(PracticeSessionItem.session_id == session_id)
            .order_by(PracticeSessionItem.position)
        )
    )
    if format == "md":
        md_text = build_recitation_md(session, items)
        return Response(
            content=md_text.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="recitation.md"'},
        )
    pdf = render_recitation_pdf(session, items)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="recitation.pdf"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/practice-sessions/{session_id}/review-rounds")
def create_round(
    request: Request,
    session_id: int,
    payload: RoundCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("reviews:write", "practice:read"))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
):
    idem = claim(
        db,
        actor=actor,
        method="POST",
        route_template="/api/v1/practice-sessions/{session_id}/review-rounds",
        key=idempotency_key,
        payload={"session_id": session_id, **payload.model_dump(mode="json")},
        required=True,
    )
    if idem and idem.replayed:
        return _idem_response(request, idem)
    session = _session(db, session_id)
    if session.status != "active":
        raise AppError(409, "INVALID_STATE", "复习表已归档")
    item_count = db.scalar(
        select(func.count())
        .select_from(PracticeSessionItem)
        .where(PracticeSessionItem.session_id == session.id)
    ) or 0
    if item_count == 0:
        raise AppError(409, "INVALID_STATE", "复习表为空，无法开始复习")
    now = utc_text()
    round_ = PracticeReviewRound(
        session_id=session.id,
        mode=payload.mode,
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
        started_at=utc_text(payload.started_at) if payload.started_at else now,
        created_at=now,
        updated_at=now,
    )
    db.add(round_)
    db.flush()
    # Starting a new round re-opens a finished session: clear the completion
    # marker so the worksheet status flips 已完成 -> 进行中.
    if session.completed_at is not None:
        session.completed_at = None
        session.version += 1
    data = round_data(db, round_)
    complete(idem, data=data, status_code=201, resource_type="practice_review_round", resource_id=round_.id)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="review_round.create",
        outcome="success",
        http_status=201,
        target_type="practice_review_round",
        target_id=round_.id,
    )
    _commit(db)
    return envelope(request, data, status_code=201)


@router.get("/practice-review-rounds/{round_id}")
def get_round(
    request: Request,
    round_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("practice:read"))],
):
    round_ = db.get(PracticeReviewRound, round_id)
    if round_ is None:
        raise not_found("practice review round")
    return envelope(request, round_data(db, round_))


@router.put("/practice-review-rounds/{round_id}/items/{item_id}/result")
def put_result(
    request: Request,
    round_id: int,
    item_id: int,
    payload: RoundResult,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("reviews:write"))],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    idem = claim(
        db,
        actor=actor,
        method="PUT",
        route_template="/api/v1/practice-review-rounds/{round_id}/items/{item_id}/result",
        key=idempotency_key,
        payload={"round_id": round_id, "item_id": item_id, **payload.model_dump(mode="json")},
        required=actor.actor_type == "api_client",
    )
    if idem and idem.replayed:
        return _idem_response(request, idem)
    log, stats, created = put_round_result(db, round_id, item_id, payload, actor)
    data = review_data(log, stats)
    status_code = 201 if created else 200
    complete(idem, data=data, status_code=status_code, resource_type="review_log", resource_id=log.id)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="review.create" if created else "review.correct",
        outcome="success",
        http_status=status_code,
        target_type="review_log",
        target_id=log.id,
    )
    _commit(db)
    return envelope(request, data, status_code=status_code)


@router.put("/practice-review-rounds/{round_id}/results")
def put_results(
    request: Request,
    round_id: int,
    payload: BatchResults,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("reviews:write"))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
):
    if len(payload.items) > get_settings().max_batch_results:
        raise AppError(422, "VALIDATION_ERROR", "批量回录数量超过上限")
    idem = claim(
        db,
        actor=actor,
        method="PUT",
        route_template="/api/v1/practice-review-rounds/{round_id}/results",
        key=idempotency_key,
        payload={"round_id": round_id, **payload.model_dump(mode="json")},
        required=True,
    )
    if idem and idem.replayed:
        return _idem_response(request, idem)
    results = batch_round_results(db, round_id, payload.items, actor)
    round_ = db.get(PracticeReviewRound, round_id)
    data = {
        "round": round_data(db, round_),
        "items": [
            review_data(log, stats)
            for log, stats, _created in results
        ],
    }
    complete(idem, data=data, status_code=200, resource_type="practice_review_round", resource_id=round_id)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="review.batch_write",
        outcome="success",
        http_status=200,
        target_type="practice_review_round",
        target_id=round_id,
        metadata={"item_count": len(payload.items)},
    )
    _commit(db)
    return envelope(request, data)
