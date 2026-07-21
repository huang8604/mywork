from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import PracticeSession, PracticeSessionItem, ReviewLog, Word, WordStats
from app.schemas import StrategyRequest
from app.services.domain import canonical_json, parse_utc, utc_text
from app.services.reviews import ActorLike


PRIORITY = ("error", "due", "custom", "new")


def _error_score(stats: WordStats, recent_unknown: int, now: datetime) -> int:
    effective = stats.known_count + stats.unknown_count
    ratio = (stats.unknown_count * 10 // effective) if effective else 0
    recency_bonus = 0
    if stats.last_effective_status == "unknown" and stats.last_effective_reviewed_at:
        days = (now - parse_utc(stats.last_effective_reviewed_at)).total_seconds() / 86400
        for boundary, bonus in ((1, 8), (3, 6), (7, 4), (30, 2)):
            if days <= boundary:
                recency_bonus = bonus
                break
    return recent_unknown * 100 + stats.consecutive_unknown * 20 + ratio + recency_bonus


def generate_session(
    db: Session, payload: StrategyRequest, actor: ActorLike, skill: tuple[str, str] | None
) -> PracticeSession:
    settings = get_settings()
    requested_total = len(payload.word_ids) if payload.word_ids else (
        payload.new_words_limit
        + payload.error_words_limit
        + payload.due_words_limit
        + payload.custom_words_limit
    )
    if requested_total > settings.max_practice_words:
        raise AppError(422, "VALIDATION_ERROR", "practice word limit exceeded")
    seed = payload.seed if payload.seed is not None else random.SystemRandom().randint(0, 2_147_483_647)
    rng = random.Random(seed)
    now = datetime.now(UTC)
    now_text = utc_text(now)
    fallback_boundary = now - timedelta(days=payload.fallback_unreviewed_days)

    words = list(db.scalars(select(Word).where(Word.deleted_at.is_(None))).all())
    stats_map = {item.word_id: item for item in db.scalars(select(WordStats)).all()}
    reviewed_word_ids = set(db.scalars(select(ReviewLog.word_id).distinct()).all())
    recent_unknown: dict[int, int] = defaultdict(int)
    seven_days_ago = utc_text(now - timedelta(days=7))
    for word_id in db.scalars(
        select(ReviewLog.word_id).where(
            ReviewLog.status == "unknown",
            ReviewLog.reviewed_at >= seven_days_ago,
        )
    ):
        recent_unknown[word_id] += 1

    categories: dict[int, set[str]] = defaultdict(set)
    pools: dict[str, list[Word]] = {key: [] for key in PRIORITY}
    for word in words:
        stats = stats_map.get(word.id)
        if word.id not in reviewed_word_ids:
            categories[word.id].add("new")
            pools["new"].append(word)
        if stats and stats.unknown_count > 0:
            categories[word.id].add("error")
            pools["error"].append(word)
        if stats and stats.due_at and stats.due_at <= now_text:
            categories[word.id].add("due")
            pools["due"].append(word)
        elif (
            stats
            and word.id in reviewed_word_ids
            and stats.last_effective_reviewed_at
            and not stats.due_at
            and parse_utc(stats.last_effective_reviewed_at) <= fallback_boundary
        ):
            categories[word.id].add("due")
            pools["due"].append(word)
        if word.is_custom:
            categories[word.id].add("custom")
            pools["custom"].append(word)

    pools["error"].sort(
        key=lambda word: (
            -_error_score(stats_map[word.id], recent_unknown[word.id], now),
            stats_map[word.id].last_effective_reviewed_at or "",
            word.id,
        )
    )
    for category in ("due", "custom", "new"):
        pools[category].sort(key=lambda word: word.id)
        rng.shuffle(pools[category])

    if payload.word_ids:
        words_by_id = {word.id: word for word in words}
        missing_ids = [word_id for word_id in payload.word_ids if word_id not in words_by_id]
        if missing_ids:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "custom selection contains missing or deleted words",
                [{"path": ["body", "word_ids"], "reason": "unavailable word ids", "value": missing_ids}],
            )
        selected = [words_by_id[word_id] for word_id in payload.word_ids]
        requested = {"selected": len(selected)}
        actual = {"unique_total": len(selected), "selected": len(selected)}
    else:
        limits = {
            "new": payload.new_words_limit,
            "error": payload.error_words_limit,
            "due": payload.due_words_limit,
            "custom": payload.custom_words_limit,
        }
        selected = []
        selected_ids: set[int] = set()
        contribution_counts = {key: 0 for key in PRIORITY}
        for category in PRIORITY:
            for word in pools[category]:
                if contribution_counts[category] >= limits[category]:
                    break
                if word.id in selected_ids:
                    continue
                selected.append(word)
                selected_ids.add(word.id)
                contribution_counts[category] += 1
                if len(selected) >= settings.max_practice_words:
                    break
        requested = {key: limits[key] for key in ("new", "error", "due", "custom")}
        actual = {"unique_total": len(selected)}
        for category in ("new", "error", "due", "custom"):
            actual[category] = sum(1 for word in selected if category in categories[word.id])

    params = payload.model_dump()
    params["seed"] = seed
    params_json = canonical_json(params)
    session = PracticeSession(
        strategy_version="v2",
        strategy_params_json=params_json,
        strategy_hash=hashlib.sha256(params_json.encode("utf-8")).hexdigest(),
        seed=seed,
        requested_counts_json=canonical_json(requested),
        actual_counts_json=canonical_json(actual),
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
        skill_name=skill[0] if skill else None,
        skill_version=skill[1] if skill else None,
        generated_at=now_text,
    )
    db.add(session)
    db.flush()
    for position, word in enumerate(selected, 1):
        word_categories = (
            ["selected"]
            if payload.word_ids
            else [key for key in PRIORITY if key in categories[word.id]]
        )
        reason = _reason(word, stats_map.get(word.id), word_categories, recent_unknown[word.id])
        db.add(
            PracticeSessionItem(
                session_id=session.id,
                word_id=word.id,
                position=position,
                snapshot_en_word=word.en_word,
                snapshot_phonetic=word.phonetic,
                snapshot_cn_meaning=word.cn_meaning,
                snapshot_example_sentence=word.example_sentence,
                source_categories_json=canonical_json(word_categories),
                reason=reason,
                created_at=now_text,
            )
        )
    db.flush()
    return session


def _reason(
    word: Word, stats: WordStats | None, categories: list[str], recent_unknown: int
) -> str:
    if "error" in categories and stats:
        return f"最近7天不认识{recent_unknown}次，连续不认识{stats.consecutive_unknown}次"
    if "due" in categories and stats:
        return f"已到期：{stats.due_at or stats.last_effective_reviewed_at}"
    if "custom" in categories:
        return "自定义词"
    if "selected" in categories:
        return "用户明确选择"
    return "尚无复习记录的新词"
