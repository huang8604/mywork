"""Add the administrator issue and requirement notebook.

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 creates all tables known to the current model on a fresh database.
    # Existing installations still need this migration, while fresh installs
    # have the table already, so keep the upgrade idempotent.
    if "system_issue_notes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "system_issue_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_system_issue_notes_singleton"),
        sa.CheckConstraint("version > 0", name="ck_system_issue_notes_version"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("system_issue_notes")
