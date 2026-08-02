"""Add explicit practice-session lifecycle statuses.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _recover_stale_batch_table() -> None:
    """Recover from an interrupted SQLite batch-table rebuild."""
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    tables = set(sa.inspect(bind).get_table_names())
    temporary = "_alembic_tmp_practice_sessions"
    original = "practice_sessions"
    if temporary in tables and original in tables:
        op.execute("DROP TABLE IF EXISTS _alembic_tmp_practice_sessions")
    elif temporary in tables:
        op.rename_table(temporary, original)


def upgrade() -> None:
    _recover_stale_batch_table()
    with op.batch_alter_table("practice_sessions") as batch:
        batch.drop_constraint("ck_sessions_status", type_="check")
        batch.create_check_constraint(
            "ck_sessions_status",
            "status IN ('not_started','active','completed','archived')",
        )
    op.execute(
        "UPDATE practice_sessions SET status = 'completed' "
        "WHERE status = 'active' AND completed_at IS NOT NULL"
    )
    op.execute(
        "UPDATE practice_sessions SET status = 'not_started' "
        "WHERE status = 'active' AND completed_at IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM practice_review_rounds "
        "WHERE practice_review_rounds.session_id = practice_sessions.id)"
    )


def downgrade() -> None:
    _recover_stale_batch_table()
    op.execute(
        "UPDATE practice_sessions SET status = 'active' "
        "WHERE status IN ('not_started','completed')"
    )
    with op.batch_alter_table("practice_sessions") as batch:
        batch.drop_constraint("ck_sessions_status", type_="check")
        batch.create_check_constraint(
            "ck_sessions_status", "status IN ('active','archived')"
        )
