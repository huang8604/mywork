"""Persist administrator-managed TTS runtime tuning (import toggle + volc knobs).

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("system_audio_settings")}
    columns = {
        "auto_generate_on_import": sa.Boolean(),
        "volc_resource_id": sa.String(length=64),
        "volc_speech_rate": sa.Integer(),
        "volc_loudness_rate": sa.Integer(),
        "volc_silence_ms": sa.Integer(),
    }
    for name, column_type in columns.items():
        if name not in existing:
            op.add_column("system_audio_settings", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in (
        "volc_silence_ms",
        "volc_loudness_rate",
        "volc_speech_rate",
        "volc_resource_id",
        "auto_generate_on_import",
    ):
        op.drop_column("system_audio_settings", name)
