"""Practice-session lifecycle operations.

Sessions are archived instead of physically deleted because their review logs
are the source of truth for word statistics.  Removing a worksheet from the
default list must therefore never erase the learner's accumulated results.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.models import PracticeSession
from app.schemas import SessionUpdate
from app.services.domain import utc_text

AUTO_ARCHIVE_DAYS = 15


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
    if session.status != "archived":
        session.status = "archived"
        session.archived_at = utc_text()
        session.version += 1
    db.flush()


def auto_archive_expired_sessions(
    db: Session,
    *,
    now: datetime | None = None,
    days: int = AUTO_ARCHIVE_DAYS,
) -> int:
    """Archive active worksheets whose generation time is at least ``days`` old."""

    moment = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff = utc_text(moment - timedelta(days=days))
    archived_at = utc_text(moment)
    result = db.execute(
        update(PracticeSession)
        .where(
            PracticeSession.status == "active",
            PracticeSession.generated_at <= cutoff,
        )
        .values(
            status="archived",
            archived_at=archived_at,
            version=PracticeSession.version + 1,
        )
    )
    db.flush()
    return int(result.rowcount or 0)
