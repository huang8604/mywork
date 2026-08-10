"""Add the persistent default audio provider setting.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "system_audio_settings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "system_audio_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("default_provider", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.String(length=32), nullable=False),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_system_audio_settings_singleton"),
        sa.CheckConstraint(
            "default_provider IN ('mimo','volc')",
            name="ck_system_audio_settings_provider",
        ),
        sa.CheckConstraint("version > 0", name="ck_system_audio_settings_version"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("system_audio_settings")
