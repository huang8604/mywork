"""Add title and note to practice_sessions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the schema via Base.metadata.create_all, which already emits
    # columns present on the current model — so title/note may already exist on
    # a fresh DB. Guard each add_column to keep the migration idempotent.
    existing = {c["name"] for c in inspect(op.get_bind()).get_columns("practice_sessions")}
    if "title" not in existing:
        op.add_column("practice_sessions", sa.Column("title", sa.String(length=200), nullable=True))
    if "note" not in existing:
        op.add_column("practice_sessions", sa.Column("note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("practice_sessions", "note")
    op.drop_column("practice_sessions", "title")
