"""Update (title/note) and hard-delete a practice session.

Delete is non-trivial because ``ReviewLog.session_item_id`` / ``review_round_id``
are ``ondelete=RESTRICT``: the session's review logs must be removed first (and
the affected words' stats rebuilt from the surviving log stream) before the
session itself can be deleted, which cascades to its items and rounds.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.models import PracticeReviewRound, PracticeSession, PracticeSessionItem, ReviewLog
from app.schemas import SessionUpdate
from app.services.reviews import rebuild_word_stats


def update_session(db: Session, session_id: int, payload: SessionUpdate) -> PracticeSession:
    session = db.get(PracticeSession, session_id)
    if session is None:
        raise not_found("practice session")
    if session.version != payload.expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "复习表已被修改，请刷新后重试",
            [{"current_version": session.version}],
        )
    session.title = payload.title
    session.note = payload.note
    session.version += 1
    db.flush()
    return session


def delete_session(db: Session, session_id: int, expected_version: int) -> None:
    session = db.get(PracticeSession, session_id)
    if session is None:
        raise not_found("practice session")
    if session.version != expected_version:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "复习表已被修改，请刷新后重试",
            [{"current_version": session.version}],
        )
    # Drop this session's review logs first (RESTRICT would otherwise block the
    # cascade), then rebuild stats for the affected words from what remains.
    item_ids = select(PracticeSessionItem.id).where(PracticeSessionItem.session_id == session_id)
    round_ids = select(PracticeReviewRound.id).where(PracticeReviewRound.session_id == session_id)
    affected_logs = list(
        db.scalars(
            select(ReviewLog).where(
                or_(
                    ReviewLog.session_item_id.in_(item_ids),
                    ReviewLog.review_round_id.in_(round_ids),
                )
            )
        )
    )
    affected_word_ids = {log.word_id for log in affected_logs}
    for log in affected_logs:
        db.delete(log)
    db.flush()
    for word_id in affected_word_ids:
        rebuild_word_stats(db, word_id)
    db.delete(session)  # ON CASCADE removes items + rounds
    db.flush()
