"""Add word audio metadata columns."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    cols = _columns("words")
    with op.batch_alter_table("words") as batch:
        if "audio_path" not in cols:
            batch.add_column(sa.Column("audio_path", sa.String(length=255), nullable=True))
        if "audio_format" not in cols:
            batch.add_column(sa.Column("audio_format", sa.String(length=16), nullable=True))
        if "audio_voice" not in cols:
            batch.add_column(sa.Column("audio_voice", sa.String(length=64), nullable=True))
        if "audio_generated_at" not in cols:
            batch.add_column(sa.Column("audio_generated_at", sa.String(length=32), nullable=True))
        if "audio_bytes" not in cols:
            batch.add_column(sa.Column("audio_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    cols = _columns("words")
    with op.batch_alter_table("words") as batch:
        for name in ["audio_bytes", "audio_generated_at", "audio_voice", "audio_format", "audio_path"]:
            if name in cols:
                batch.drop_column(name)
