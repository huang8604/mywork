from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.models import (
    PracticeReviewRound,
    PracticeSession,
    PracticeSessionItem,
    ReviewLog,
    Word,
    WordStats,
)
from app.schemas import BatchRoundResult, ReviewCorrection, ReviewCreate, RoundResult
from app.services.domain import calculate_stats, reviewed_at_text, utc_text


@dataclass(frozen=True)
class ActorLike:
    actor_type: str
    actor_id: str


def rebuild_word_stats(db: Session, word_id: int) -> WordStats:
    logs = db.scalars(
        select(ReviewLog)
        .where(ReviewLog.word_id == word_id)
        .order_by(ReviewLog.reviewed_at.asc(), ReviewLog.id.asc())
    ).all()
    values = calculate_stats(logs)
    stats = db.get(WordStats, word_id)
    if stats is None:
        stats = WordStats(word_id=word_id)
        db.add(stats)
    for key, value in values.items():
        setattr(stats, key, value)
    stats.updated_at = utc_text()
    db.flush()
    return stats


def rebuild_all_stats(db: Session) -> int:
    word_ids = db.scalars(select(Word.id)).all()
    for word_id in word_ids:
        rebuild_word_stats(db, word_id)
    return len(word_ids)


def _same_event(
    log: ReviewLog, status: str, word_id: int, reviewed_at: str | None
) -> bool:
    return (
        log.status == status
        and log.word_id == word_id
        and (reviewed_at is None or log.reviewed_at == reviewed_at)
    )


def create_quick_review(
    db: Session, payload: ReviewCreate, actor: ActorLike
) -> tuple[ReviewLog, WordStats, bool]:
    word = db.get(Word, payload.word_id)
    if word is None or word.deleted_at:
        raise not_found("word")
    existing = db.scalar(
        select(ReviewLog).where(
            ReviewLog.actor_type == actor.actor_type,
            ReviewLog.actor_id == actor.actor_id,
            ReviewLog.client_event_id == payload.client_event_id,
        )
    )
    if existing is not None:
        supplied_time = reviewed_at_text(payload.reviewed_at) if payload.reviewed_at else None
        if _same_event(existing, payload.status, payload.word_id, supplied_time):
            return existing, rebuild_word_stats(db, existing.word_id), True
        raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "client_event_id is already used")
    reviewed_at = reviewed_at_text(payload.reviewed_at)
    now = utc_text()
    result = db.execute(
        sqlite_insert(ReviewLog)
        .values(
            word_id=word.id,
            status=payload.status,
            source="quick_review",
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            client_event_id=payload.client_event_id,
            duration_ms=payload.duration_ms,
            reviewed_at=reviewed_at,
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["actor_type", "actor_id", "client_event_id"]
        )
    )
    log = db.scalar(
        select(ReviewLog).where(
            ReviewLog.actor_type == actor.actor_type,
            ReviewLog.actor_id == actor.actor_id,
            ReviewLog.client_event_id == payload.client_event_id,
        )
    )
    if log is None:
        raise AppError(503, "SERVICE_BUSY", "could not write review")
    if result.rowcount == 0:
        supplied_time = reviewed_at_text(payload.reviewed_at) if payload.reviewed_at else None
        if _same_event(log, payload.status, payload.word_id, supplied_time):
            return log, rebuild_word_stats(db, log.word_id), True
        raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "client_event_id is already used")
    return log, rebuild_word_stats(db, word.id), False


def correct_review(
    db: Session, review_id: int, payload: ReviewCorrection, actor: ActorLike
) -> tuple[ReviewLog, WordStats]:
    log = db.get(ReviewLog, review_id)
    if log is None:
        raise not_found("review")
    if actor.actor_type == "api_client" and (
        log.actor_type != "api_client" or log.actor_id != actor.actor_id
    ):
        raise AppError(403, "FORBIDDEN_SCOPE", "cannot modify another actor's review")
    if log.client_event_id != payload.client_event_id:
        raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "client_event_id does not match")
    if log.version != payload.expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "review was modified",
            [{"current_version": log.version}],
        )
    values: dict[str, object] = {
        "status": payload.status,
        "duration_ms": payload.duration_ms,
        "version": payload.expected_version + 1,
        "updated_at": utc_text(),
    }
    if payload.reviewed_at is not None:
        values["reviewed_at"] = reviewed_at_text(payload.reviewed_at)
    result = db.execute(
        update(ReviewLog)
        .where(
            ReviewLog.id == review_id,
            ReviewLog.version == payload.expected_version,
        )
        .values(**values)
    )
    if result.rowcount != 1:
        current_version = db.scalar(
            select(ReviewLog.version).where(ReviewLog.id == review_id)
        )
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "review was modified",
            [{"current_version": current_version}],
        )
    db.expire(log)
    db.refresh(log)
    stats = rebuild_word_stats(db, log.word_id)
    if log.session_item_id is not None:
        _refresh_item_and_round(db, log.session_item_id, log.review_round_id)
    return log, stats


def _round_context(
    db: Session, round_id: int, item_id: int
) -> tuple[PracticeReviewRound, PracticeSession, PracticeSessionItem, Word]:
    round_ = db.get(PracticeReviewRound, round_id)
    item = db.get(PracticeSessionItem, item_id)
    if round_ is None or item is None or round_.session_id != item.session_id:
        raise not_found("round item")
    session = db.get(PracticeSession, round_.session_id)
    word = db.get(Word, item.word_id)
    if session is None or word is None:
        raise not_found("practice session")
    if word.deleted_at:
        raise AppError(409, "INVALID_STATE", "word is deleted")
    return round_, session, item, word


def _refresh_item_and_round(
    db: Session, item_id: int, round_id: int | None
) -> None:
    item = db.get(PracticeSessionItem, item_id)
    if item is None:
        return
    latest = db.scalar(
        select(ReviewLog)
        .where(ReviewLog.session_item_id == item.id)
        .order_by(ReviewLog.reviewed_at.desc(), ReviewLog.id.desc())
        .limit(1)
    )
    item.latest_review_log_id = latest.id if latest else None
    if round_id is None:
        return
    round_ = db.get(PracticeReviewRound, round_id)
    if round_ is None:
        return
    total = db.scalar(
        select(func.count())
        .select_from(PracticeSessionItem)
        .where(PracticeSessionItem.session_id == round_.session_id)
    ) or 0
    answered = db.scalar(
        select(func.count())
        .select_from(ReviewLog)
        .where(ReviewLog.review_round_id == round_.id)
    ) or 0
    now = utc_text()
    if total > 0 and answered == total and round_.status != "completed":
        round_.status = "completed"
        round_.completed_at = now
        round_.version += 1
        session = db.get(PracticeSession, round_.session_id)
        if session is not None and session.completed_at is None:
            session.completed_at = now
            session.version += 1
    round_.updated_at = now


def put_round_result(
    db: Session,
    round_id: int,
    item_id: int,
    payload: RoundResult,
    actor: ActorLike,
) -> tuple[ReviewLog, WordStats, bool]:
    round_, _session, item, word = _round_context(db, round_id, item_id)
    existing = db.scalar(
        select(ReviewLog).where(
            ReviewLog.review_round_id == round_id,
            ReviewLog.session_item_id == item_id,
        )
    )
    source = "print_manual" if round_.mode == "offline" else "online_practice"
    reviewed_at = reviewed_at_text(payload.reviewed_at)
    if existing is not None:
        correction = ReviewCorrection(
            status=payload.status,
            reviewed_at=payload.reviewed_at,
            duration_ms=payload.duration_ms,
            client_event_id=payload.client_event_id,
            expected_version=payload.expected_version or 0,
        )
        log, stats = correct_review(db, existing.id, correction, actor)
        return log, stats, False
    if round_.status == "completed":
        raise AppError(409, "INVALID_STATE", "completed round cannot accept a new item")
    if payload.expected_version is not None:
        raise AppError(422, "VALIDATION_ERROR", "expected_version is only for correction")
    event = db.scalar(
        select(ReviewLog).where(
            ReviewLog.actor_type == actor.actor_type,
            ReviewLog.actor_id == actor.actor_id,
            ReviewLog.client_event_id == payload.client_event_id,
        )
    )
    if event is not None:
        if (
            event.review_round_id == round_id
            and event.session_item_id == item_id
            and event.status == payload.status
        ):
            return event, rebuild_word_stats(db, event.word_id), False
        raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "client_event_id is already used")
    now = utc_text()
    result = db.execute(
        sqlite_insert(ReviewLog)
        .values(
            word_id=word.id,
            session_item_id=item.id,
            review_round_id=round_.id,
            status=payload.status,
            source=source,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            client_event_id=payload.client_event_id,
            duration_ms=payload.duration_ms,
            reviewed_at=reviewed_at,
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing()
    )
    log = db.scalar(
        select(ReviewLog).where(
            ReviewLog.review_round_id == round_id,
            ReviewLog.session_item_id == item_id,
        )
    )
    if log is None:
        raise AppError(503, "SERVICE_BUSY", "could not write round result")
    if result.rowcount == 0:
        if (
            log.actor_type == actor.actor_type
            and log.actor_id == actor.actor_id
            and log.client_event_id == payload.client_event_id
            and log.status == payload.status
        ):
            return log, rebuild_word_stats(db, log.word_id), False
        raise AppError(409, "IDEMPOTENCY_KEY_REUSE", "result already exists")
    stats = rebuild_word_stats(db, word.id)
    _refresh_item_and_round(db, item.id, round_.id)
    db.flush()
    return log, stats, True


def batch_round_results(
    db: Session,
    round_id: int,
    items: list[BatchRoundResult],
    actor: ActorLike,
) -> list[tuple[ReviewLog, WordStats, bool]]:
    contexts = [_round_context(db, round_id, item.item_id) for item in items]
    for payload, context in zip(items, contexts, strict=True):
        round_, _session, item, _word = context
        existing = db.scalar(
            select(ReviewLog).where(
                ReviewLog.review_round_id == round_id,
                ReviewLog.session_item_id == item.id,
            )
        )
        if existing is None and round_.status == "completed":
            raise AppError(409, "INVALID_STATE", "completed round cannot accept a new item")
        if existing is None and payload.expected_version is not None:
            raise AppError(422, "VALIDATION_ERROR", "unexpected expected_version")
        if existing is not None and payload.expected_version is None:
            raise AppError(422, "VALIDATION_ERROR", "expected_version is required")
        if existing is not None and existing.version != payload.expected_version:
            raise AppError(
                409,
                "VERSION_CONFLICT",
                "review was modified",
                [{"item_id": item.id, "current_version": existing.version}],
            )
        if existing is not None and actor.actor_type == "api_client" and (
            existing.actor_type != "api_client" or existing.actor_id != actor.actor_id
        ):
            raise AppError(403, "FORBIDDEN_SCOPE", "cannot modify another actor's review")
    results: list[tuple[ReviewLog, WordStats, bool]] = []
    for payload in items:
        results.append(put_round_result(db, round_id, payload.item_id, payload, actor))
    return results
