"""Persist administrator-managed TTS provider overrides.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("system_audio_settings")}
    columns = {
        "mimo_base_url": sa.String(length=500),
        "mimo_api_key": sa.String(length=1000),
        "mimo_model": sa.String(length=200),
        "mimo_voice": sa.String(length=200),
        "volc_base_url": sa.String(length=500),
        "volc_api_key": sa.String(length=1000),
        "volc_model": sa.String(length=200),
        "volc_voice": sa.String(length=200),
    }
    for name, column_type in columns.items():
        if name not in existing:
            op.add_column("system_audio_settings", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in (
        "volc_voice",
        "volc_model",
        "volc_api_key",
        "volc_base_url",
        "mimo_voice",
        "mimo_model",
        "mimo_api_key",
        "mimo_base_url",
    ):
        op.drop_column("system_audio_settings", name)
