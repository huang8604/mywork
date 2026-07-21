from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    PracticeReviewRound,
    PracticeSession,
    PracticeSessionItem,
    ReviewLog,
    Tag,
    Word,
    WordStats,
    WordTag,
)


def stats_data(stats: WordStats | None) -> dict[str, object]:
    if stats is None:
        return {
            "known_count": 0,
            "unknown_count": 0,
            "skipped_count": 0,
            "total_attempts": 0,
            "accuracy": None,
            "consecutive_known": 0,
            "consecutive_unknown": 0,
            "last_status": None,
            "last_reviewed_at": None,
            "last_effective_status": None,
            "last_effective_reviewed_at": None,
            "interval_days": 0,
            "due_at": None,
        }
    effective = stats.known_count + stats.unknown_count
    return {
        "known_count": stats.known_count,
        "unknown_count": stats.unknown_count,
        "skipped_count": stats.skipped_count,
        "total_attempts": effective + stats.skipped_count,
        "accuracy": stats.known_count / effective if effective else None,
        "consecutive_known": stats.consecutive_known,
        "consecutive_unknown": stats.consecutive_unknown,
        "last_status": stats.last_status,
        "last_reviewed_at": stats.last_reviewed_at,
        "last_effective_status": stats.last_effective_status,
        "last_effective_reviewed_at": stats.last_effective_reviewed_at,
        "interval_days": stats.interval_days,
        "due_at": stats.due_at,
        "updated_at": stats.updated_at,
    }


def word_data(db: Session, word: Word, *, include_stats: bool = True) -> dict[str, object]:
    tags = db.scalars(
        select(Tag.name)
        .join(WordTag, WordTag.tag_id == Tag.id)
        .where(WordTag.word_id == word.id)
        .order_by(Tag.normalized_name)
    ).all()
    data: dict[str, object] = {
        "id": word.id,
        "en_word": word.en_word,
        "normalized_en_word": word.normalized_en_word,
        "phonetic": word.phonetic,
        "cn_meaning": word.cn_meaning,
        "example_sentence": word.example_sentence,
        "is_custom": bool(word.is_custom),
        "tags": list(tags),
        "version": word.version,
        "created_at": word.created_at,
        "updated_at": word.updated_at,
        "deleted_at": word.deleted_at,
    }
    if include_stats:
        data["stats"] = stats_data(db.get(WordStats, word.id))
    return data


def review_data(log: ReviewLog, stats: WordStats | None = None) -> dict[str, object]:
    data: dict[str, object] = {
        "id": log.id,
        "word_id": log.word_id,
        "session_item_id": log.session_item_id,
        "review_round_id": log.review_round_id,
        "status": log.status,
        "source": log.source,
        "actor_type": log.actor_type,
        "actor_id": log.actor_id,
        "client_event_id": log.client_event_id,
        "duration_ms": log.duration_ms,
        "reviewed_at": log.reviewed_at,
        "version": log.version,
        "created_at": log.created_at,
        "updated_at": log.updated_at,
    }
    if stats is not None:
        data["stats"] = stats_data(stats)
    return data


def round_data(db: Session, round_: PracticeReviewRound) -> dict[str, object]:
    total = db.scalar(
        select(PracticeSessionItem.id)
        .where(PracticeSessionItem.session_id == round_.session_id)
        .with_only_columns(__import__("sqlalchemy").func.count())
    ) or 0
    answered = db.scalar(
        select(ReviewLog.id)
        .where(ReviewLog.review_round_id == round_.id)
        .with_only_columns(__import__("sqlalchemy").func.count())
    ) or 0
    return {
        "round_id": round_.id,
        "session_id": round_.session_id,
        "mode": round_.mode,
        "status": round_.status,
        "version": round_.version,
        "started_at": round_.started_at,
        "completed_at": round_.completed_at,
        "item_total": total,
        "answered_count": answered,
    }


def session_data(db: Session, session: PracticeSession, *, include_items: bool) -> dict[str, object]:
    data: dict[str, object] = {
        "session_id": session.id,
        "status": session.status,
        "strategy_version": session.strategy_version,
        "seed": session.seed,
        "strategy_params": json.loads(session.strategy_params_json),
        "requested_counts": json.loads(session.requested_counts_json),
        "actual_counts": json.loads(session.actual_counts_json),
        "created_by_actor_type": session.created_by_actor_type,
        "created_by_actor_id": session.created_by_actor_id,
        "skill_name": session.skill_name,
        "skill_version": session.skill_version,
        "version": session.version,
        "generated_at": session.generated_at,
        "printed_at": session.printed_at,
        "completed_at": session.completed_at,
        "archived_at": session.archived_at,
        "title": session.title,
        "note": session.note,
    }
    if include_items:
        items = db.scalars(
            select(PracticeSessionItem)
            .where(PracticeSessionItem.session_id == session.id)
            .order_by(PracticeSessionItem.position)
        ).all()
        data["items"] = [
            {
                "item_id": item.id,
                "position": item.position,
                "word_id": item.word_id,
                "word": {
                    "en_word": item.snapshot_en_word,
                    "phonetic": item.snapshot_phonetic,
                    "cn_meaning": item.snapshot_cn_meaning,
                    "example_sentence": item.snapshot_example_sentence,
                },
                "source_categories": json.loads(item.source_categories_json),
                "reason": item.reason,
                "latest_review_log_id": item.latest_review_log_id,
            }
            for item in items
        ]
        rounds = db.scalars(
            select(PracticeReviewRound)
            .where(PracticeReviewRound.session_id == session.id)
            .order_by(PracticeReviewRound.started_at.desc(), PracticeReviewRound.id.desc())
        ).all()
        data["rounds"] = [round_data(db, item) for item in rounds]
    return data

