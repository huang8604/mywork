from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session

from app.core.audit import add_audit
from app.core.auth import Actor, require_scopes
from app.core.database import get_db
from app.core.errors import AppError
from app.core.responses import envelope
from app.models import ReviewLog, WordStats
from app.schemas import ReviewCorrection, ReviewCreate
from app.services.reviews import correct_review, create_quick_review
from app.services.domain import utc_text
from app.services.serializers import review_data, stats_data

router = APIRouter(prefix="/api/v1", tags=["reviews"])


@router.post("/reviews")
def create_review(
    request: Request,
    payload: ReviewCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("reviews:write", "words:read"))],
):
    log, stats, replayed = create_quick_review(db, payload, actor)
    if not replayed:
        add_audit(
            db,
            request_id=request.state.request_id,
            actor=actor,
            action="review.create",
            outcome="success",
            http_status=201,
            target_type="review_log",
            target_id=log.id,
        )
    db.commit()
    return envelope(
        request,
        review_data(log, stats),
        status_code=200 if replayed else 201,
        headers={"Idempotency-Replayed": "true"} if replayed else None,
    )


@router.patch("/reviews/{review_id}")
def patch_review(
    request: Request,
    review_id: int,
    payload: ReviewCorrection,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[Actor, Depends(require_scopes("reviews:write"))],
):
    old = db.get(ReviewLog, review_id)
    before = (
        {"status": old.status, "reviewed_at": old.reviewed_at, "version": old.version}
        if old
        else None
    )
    log, stats = correct_review(db, review_id, payload, actor)
    add_audit(
        db,
        request_id=request.state.request_id,
        actor=actor,
        action="review.correct",
        outcome="success",
        http_status=200,
        target_type="review_log",
        target_id=log.id,
        metadata={
            "before": before,
            "after": {
                "status": log.status,
                "reviewed_at": log.reviewed_at,
                "version": log.version,
            },
        },
    )
    db.commit()
    return envelope(request, review_data(log, stats))


@router.get("/reviews")
def list_reviews(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("reviews:read"))],
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    word_id: int | None = None,
    status: str | None = None,
    source: str | None = None,
    actor_type: str | None = None,
    session_id: int | None = None,
    round_id: int | None = None,
    reviewed_from: str | None = None,
    reviewed_to: str | None = None,
    sort: str = "reviewed_at_desc",
):
    if status and status not in {"known", "unknown", "skipped"}:
        raise AppError(422, "VALIDATION_ERROR", "invalid status")
    if source and source not in {"quick_review", "online_practice", "print_manual"}:
        raise AppError(422, "VALIDATION_ERROR", "invalid source")
    if actor_type and actor_type not in {"web_user", "api_client"}:
        raise AppError(422, "VALIDATION_ERROR", "invalid actor_type")
    if sort not in {"reviewed_at_desc", "reviewed_at_asc"}:
        raise AppError(422, "VALIDATION_ERROR", "invalid sort")
    if reviewed_from and reviewed_to and reviewed_from > reviewed_to:
        raise AppError(422, "VALIDATION_ERROR", "invalid reviewed range")
    filters = []
    for column, value in (
        (ReviewLog.word_id, word_id),
        (ReviewLog.status, status),
        (ReviewLog.source, source),
        (ReviewLog.actor_type, actor_type),
        (ReviewLog.review_round_id, round_id),
    ):
        if value is not None:
            filters.append(column == value)
    if reviewed_from:
        filters.append(ReviewLog.reviewed_at >= reviewed_from)
    if reviewed_to:
        filters.append(ReviewLog.reviewed_at <= reviewed_to)
    if session_id is not None:
        from app.models import PracticeReviewRound

        filters.append(
            ReviewLog.review_round_id.in_(
                select(PracticeReviewRound.id).where(
                    PracticeReviewRound.session_id == session_id
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(ReviewLog).where(and_(*filters))) or 0
    ordering = (
        (desc(ReviewLog.reviewed_at), desc(ReviewLog.id))
        if sort.endswith("desc")
        else (asc(ReviewLog.reviewed_at), asc(ReviewLog.id))
    )
    logs = db.scalars(
        select(ReviewLog)
        .where(and_(*filters))
        .order_by(*ordering)
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return envelope(
        request,
        [review_data(log) for log in logs],
        meta={"page": page, "size": size, "total": total},
    )


@router.get("/stats/summary")
def stats_summary(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("reviews:read"))],
):
    totals = db.execute(
        select(
            func.coalesce(func.sum(WordStats.known_count), 0),
            func.coalesce(func.sum(WordStats.unknown_count), 0),
            func.coalesce(func.sum(WordStats.skipped_count), 0),
            func.count(WordStats.word_id),
            func.sum(func.iif(WordStats.due_at <= utc_text(), 1, 0)),
        )
    ).one()
    known, unknown, skipped, reviewed_words, due_words = [int(value or 0) for value in totals]
    effective = known + unknown
    return envelope(
        request,
        {
            "known_count": known,
            "unknown_count": unknown,
            "skipped_count": skipped,
            "total_attempts": effective + skipped,
            "accuracy": known / effective if effective else None,
            "reviewed_words": reviewed_words,
            "due_words": due_words,
        },
    )


@router.get("/words/{word_id}/stats")
def word_stats(
    request: Request,
    word_id: int,
    db: Annotated[Session, Depends(get_db)],
    _actor: Annotated[Actor, Depends(require_scopes("words:read", "reviews:read"))],
):
    from app.services.words import get_word

    get_word(db, word_id)
    stats = db.get(WordStats, word_id)
    recent = db.scalars(
        select(ReviewLog)
        .where(ReviewLog.word_id == word_id)
        .order_by(ReviewLog.reviewed_at.desc(), ReviewLog.id.desc())
        .limit(20)
    ).all()
    return envelope(
        request,
        {"summary": stats_data(stats), "recent_reviews": [review_data(item) for item in recent]},
    )
