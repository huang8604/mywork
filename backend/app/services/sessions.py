"""Practice-session lifecycle operations.

Sessions are archived instead of physically deleted because their review logs
are the source of truth for word statistics.  Removing a worksheet from the
default list must therefore never erase the learner's accumulated results.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.models import PracticeReviewRound, PracticeSession, PracticeSessionItem, Word
from app.schemas import SessionItemsUpdate, SessionUpdate
from app.services.domain import canonical_json, utc_text

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


def replace_session_items(
    db: Session, session_id: int, payload: SessionItemsUpdate
) -> PracticeSession:
    """Replace a worksheet's ordered word list before any review round exists."""

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
    if session.status != "active":
        raise AppError(409, "INVALID_STATE", "已归档的复习表不能修改单词")
    if db.scalar(
        select(PracticeReviewRound.id)
        .where(PracticeReviewRound.session_id == session_id)
        .limit(1)
    ) is not None:
        raise AppError(409, "INVALID_STATE", "已有复习轮次，不能再增删单词")
    if len(payload.word_ids) > get_settings().max_practice_words:
        raise AppError(422, "VALIDATION_ERROR", "练习单词数量超过上限")

    words = list(
        db.scalars(
            select(Word).where(
                Word.id.in_(payload.word_ids),
                Word.deleted_at.is_(None),
            )
        )
    )
    words_by_id = {word.id: word for word in words}
    missing_ids = [word_id for word_id in payload.word_ids if word_id not in words_by_id]
    if missing_ids:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "复习表包含不存在或已删除的词",
            [{"path": ["body", "word_ids"], "reason": "包含不可用的单词 ID", "value": missing_ids}],
        )

    claimed = db.execute(
        update(PracticeSession)
        .where(
            PracticeSession.id == session_id,
            PracticeSession.version == payload.expected_version,
        )
        .values(version=PracticeSession.version + 1)
    )
    if int(claimed.rowcount or 0) != 1:
        db.expire(session)
        raise AppError(409, "VERSION_CONFLICT", "复习表已被修改，请刷新后重试")
    db.refresh(session)

    db.execute(
        delete(PracticeSessionItem).where(PracticeSessionItem.session_id == session_id)
    )
    db.flush()
    now = utc_text()
    for position, word_id in enumerate(payload.word_ids, 1):
        word = words_by_id[word_id]
        db.add(
            PracticeSessionItem(
                session_id=session.id,
                word_id=word.id,
                position=position,
                snapshot_en_word=word.en_word,
                snapshot_phonetic=word.phonetic,
                snapshot_cn_meaning=word.cn_meaning,
                snapshot_example_sentence=word.example_sentence,
                source_categories_json=canonical_json(["selected"]),
                reason="用户编辑复习表",
                created_at=now,
            )
        )

    params = {
        "new_words_limit": 0,
        "error_words_limit": 0,
        "due_words_limit": 0,
        "custom_words_limit": 0,
        "total_words": None,
        "fallback_unreviewed_days": 3,
        "seed": session.seed,
        "word_ids": payload.word_ids,
    }
    params_json = canonical_json(params)
    session.strategy_params_json = params_json
    session.strategy_hash = hashlib.sha256(params_json.encode("utf-8")).hexdigest()
    session.requested_counts_json = canonical_json({"selected": len(payload.word_ids)})
    session.actual_counts_json = canonical_json(
        {"unique_total": len(payload.word_ids), "selected": len(payload.word_ids)}
    )
    session.printed_at = None
    session.completed_at = None
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
