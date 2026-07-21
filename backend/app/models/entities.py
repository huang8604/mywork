from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (
        CheckConstraint("length(en_word) BETWEEN 1 AND 200", name="ck_words_en_word_length"),
        CheckConstraint("length(normalized_en_word) BETWEEN 1 AND 200", name="ck_words_normalized_length"),
        CheckConstraint("is_custom IN (0, 1)", name="ck_words_is_custom"),
        CheckConstraint("version > 0", name="ck_words_version"),
        Index("ix_words_deleted_created", "deleted_at", text("created_at DESC"), text("id DESC")),
        Index("ix_words_custom_deleted", "is_custom", "deleted_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    en_word: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_en_word: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    phonetic: Mapped[str | None] = mapped_column(String(200))
    cn_meaning: Mapped[str] = mapped_column(Text, nullable=False)
    example_sentence: Mapped[str | None] = mapped_column(Text)
    is_custom: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    deleted_at: Mapped[str | None] = mapped_column(String(32))


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint("length(name) BETWEEN 1 AND 50", name="ck_tags_name_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)


class WordTag(Base):
    __tablename__ = "word_tags"
    __table_args__ = (Index("ix_word_tags_tag_word", "tag_id", "word_id"),)

    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class WordStats(Base):
    __tablename__ = "word_stats"
    __table_args__ = (
        CheckConstraint("known_count >= 0", name="ck_stats_known"),
        CheckConstraint("unknown_count >= 0", name="ck_stats_unknown"),
        CheckConstraint("skipped_count >= 0", name="ck_stats_skipped"),
        CheckConstraint("consecutive_known >= 0", name="ck_stats_consecutive_known"),
        CheckConstraint("consecutive_unknown >= 0", name="ck_stats_consecutive_unknown"),
        CheckConstraint(
            "NOT (consecutive_known > 0 AND consecutive_unknown > 0)",
            name="ck_stats_consecutive_exclusive",
        ),
        CheckConstraint("interval_days >= 0", name="ck_stats_interval"),
        CheckConstraint(
            "last_status IS NULL OR last_status IN ('known','unknown','skipped')",
            name="ck_stats_last_status",
        ),
        CheckConstraint(
            "last_effective_status IS NULL OR last_effective_status IN ('known','unknown')",
            name="ck_stats_last_effective_status",
        ),
        Index(
            "ix_stats_due",
            "due_at",
            "word_id",
            sqlite_where=text("due_at IS NOT NULL"),
        ),
    )

    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), primary_key=True
    )
    known_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_known: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_unknown: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_reviewed_at: Mapped[str | None] = mapped_column(String(32))
    last_effective_status: Mapped[str | None] = mapped_column(String(16))
    last_effective_reviewed_at: Mapped[str | None] = mapped_column(String(32))
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_at: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_sessions_status"),
        CheckConstraint("seed BETWEEN 0 AND 2147483647", name="ck_sessions_seed"),
        CheckConstraint("version > 0", name="ck_sessions_version"),
        CheckConstraint(
            "created_by_actor_type IN ('web_user','api_client')",
            name="ck_sessions_actor_type",
        ),
        Index("ix_sessions_status_generated", "status", text("generated_at DESC"), text("id DESC")),
        Index(
            "ix_sessions_actor_generated",
            "created_by_actor_type",
            "created_by_actor_id",
            text("generated_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    strategy_version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    strategy_params_json: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    actual_counts_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    skill_name: Mapped[str | None] = mapped_column(String(100))
    skill_version: Mapped[str | None] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generated_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    printed_at: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[str | None] = mapped_column(String(32))
    archived_at: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)


class PracticeSessionItem(Base):
    __tablename__ = "practice_session_items"
    __table_args__ = (
        UniqueConstraint("session_id", "word_id", name="uq_session_items_word"),
        UniqueConstraint("session_id", "position", name="uq_session_items_position"),
        CheckConstraint("position > 0", name="ck_session_items_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False
    )
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_en_word: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot_phonetic: Mapped[str | None] = mapped_column(String(200))
    snapshot_cn_meaning: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_example_sentence: Mapped[str | None] = mapped_column(Text)
    source_categories_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    latest_review_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("review_logs.id", ondelete="SET NULL")
    )
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)


class PracticeReviewRound(Base):
    __tablename__ = "practice_review_rounds"
    __table_args__ = (
        CheckConstraint("mode IN ('offline','online')", name="ck_rounds_mode"),
        CheckConstraint("status IN ('open','completed')", name="ck_rounds_status"),
        CheckConstraint(
            "created_by_actor_type IN ('web_user','api_client')",
            name="ck_rounds_actor_type",
        ),
        CheckConstraint("version > 0", name="ck_rounds_version"),
        Index("ix_rounds_session_started", "session_id", text("started_at DESC"), text("id DESC")),
        Index("ix_rounds_status_started", "status", text("started_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_by_actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)


class ReviewLog(Base):
    __tablename__ = "review_logs"
    __table_args__ = (
        UniqueConstraint(
            "actor_type", "actor_id", "client_event_id", name="uq_reviews_actor_event"
        ),
        UniqueConstraint(
            "review_round_id", "session_item_id", name="uq_reviews_round_item"
        ),
        CheckConstraint("status IN ('known','unknown','skipped')", name="ck_reviews_status"),
        CheckConstraint(
            "source IN ('quick_review','online_practice','print_manual')",
            name="ck_reviews_source",
        ),
        CheckConstraint(
            "actor_type IN ('web_user','api_client')", name="ck_reviews_actor_type"
        ),
        CheckConstraint(
            "(session_item_id IS NULL) = (review_round_id IS NULL)",
            name="ck_reviews_refs_together",
        ),
        CheckConstraint(
            "(source = 'quick_review' AND session_item_id IS NULL AND review_round_id IS NULL) "
            "OR (source IN ('online_practice','print_manual') "
            "AND session_item_id IS NOT NULL AND review_round_id IS NOT NULL)",
            name="ck_reviews_source_refs",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms BETWEEN 0 AND 86400000",
            name="ck_reviews_duration",
        ),
        CheckConstraint("version > 0", name="ck_reviews_version"),
        Index("ix_reviews_word_time", "word_id", text("reviewed_at DESC"), text("id DESC")),
        Index("ix_reviews_status_time", "status", text("reviewed_at DESC"), text("id DESC")),
        Index("ix_reviews_source_time", "source", text("reviewed_at DESC"), text("id DESC")),
        Index("ix_reviews_round_item", "review_round_id", "session_item_id"),
        Index("ix_reviews_actor_time", "actor_type", "actor_id", text("reviewed_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="RESTRICT"), nullable=False
    )
    session_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("practice_session_items.id", ondelete="RESTRICT")
    )
    review_round_id: Mapped[int | None] = mapped_column(
        ForeignKey("practice_review_rounds.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)


class ApiClient(Base):
    __tablename__ = "api_clients"
    __table_args__ = (
        CheckConstraint("status IN ('active','disabled')", name="ck_clients_status"),
        CheckConstraint("scope_version > 0", name="ck_clients_scope_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    scope_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)


class ApiClientScope(Base):
    __tablename__ = "api_client_scopes"

    api_client_id: Mapped[int] = mapped_column(
        ForeignKey("api_clients.id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)


class ApiClientToken(Base):
    __tablename__ = "api_client_tokens"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_tokens_expiry"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_tokens_revoked"
        ),
        Index("ix_tokens_prefix", "token_prefix"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    api_client_id: Mapped[int] = mapped_column(
        ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=False
    )
    token_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    expires_at: Mapped[str] = mapped_column(String(32), nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(String(32))
    revoked_at: Mapped[str | None] = mapped_column(String(32))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "actor_type",
            "actor_id",
            "method",
            "route_template",
            "idempotency_key",
            name="uq_idempotency_actor_request",
        ),
        CheckConstraint(
            "actor_type IN ('web_user','api_client')", name="ck_idempotency_actor"
        ),
        CheckConstraint("state IN ('processing','succeeded')", name="ck_idempotency_state"),
        Index("ix_idempotency_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    route_template: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="processing")
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    expires_at: Mapped[str] = mapped_column(String(32), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('anonymous','web_user','api_client','system')",
            name="ck_audit_actor",
        ),
        CheckConstraint("outcome IN ('success','denied','failed')", name="ck_audit_outcome"),
        CheckConstraint("latency_ms >= 0", name="ck_audit_latency"),
        Index("ix_audit_time", text("occurred_at DESC"), text("id DESC")),
        Index("ix_audit_client_time", "api_client_id", text("occurred_at DESC")),
        Index("ix_audit_request", "request_id"),
        Index("ix_audit_action_outcome", "action", "outcome", text("occurred_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[str] = mapped_column(String(32), nullable=False, default=utc_now_text)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    api_client_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_clients.id", ondelete="SET NULL")
    )
    skill_name: Mapped[str | None] = mapped_column(String(100))
    skill_version: Mapped[str | None] = mapped_column(String(50))
    scopes_json: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remote_addr_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[str | None] = mapped_column(Text)

