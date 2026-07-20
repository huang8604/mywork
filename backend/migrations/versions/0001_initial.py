"""Initial schema v1.

Revision ID: 0001
Revises:
Create Date: 2026-07-20
"""
from __future__ import annotations

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
    Base.metadata.drop_all(bind=connection, checkfirst=True)
    connection.exec_driver_sql("PRAGMA foreign_keys = ON")
