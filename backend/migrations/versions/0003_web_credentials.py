"""Add web_credentials for login.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 builds the schema via Base.metadata.create_all(checkfirst=True), which
    # already emits tables present on the current model — so web_credentials may
    # already exist on a fresh DB. Guard to keep the migration idempotent (same
    # pattern as 0002's add_column guards).
    bind = op.get_bind()
    if "web_credentials" in inspect(bind).get_table_names():
        return
    op.create_table(
        "web_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="admin"),
        sa.Column("disabled_at", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "length(username) BETWEEN 1 AND 64", name="ck_web_credentials_username_length"
        ),
        sa.CheckConstraint("role IN ('admin','student')", name="ck_web_credentials_role"),
        sa.UniqueConstraint("username", name="uq_web_credentials_username"),
    )


def downgrade() -> None:
    op.drop_table("web_credentials")
