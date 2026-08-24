"""Persist the single custom TTS API connection used by the current UI.

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("system_audio_settings")}
    if "custom_base_url" not in existing:
        op.add_column(
            "system_audio_settings",
            sa.Column("custom_base_url", sa.String(length=500), nullable=True),
        )
    if "custom_api_key" not in existing:
        op.add_column(
            "system_audio_settings",
            sa.Column("custom_api_key", sa.String(length=1000), nullable=True),
        )
    # Carry the previous primary (mimo) account into the new single-account
    # fields.  This keeps an existing deployment configured after upgrading.
    op.execute(
        "UPDATE system_audio_settings "
        "SET custom_base_url = COALESCE(custom_base_url, mimo_base_url), "
        "custom_api_key = COALESCE(custom_api_key, mimo_api_key)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("system_audio_settings")}
    for name in ("custom_api_key", "custom_base_url"):
        if name in existing:
            op.drop_column("system_audio_settings", name)
