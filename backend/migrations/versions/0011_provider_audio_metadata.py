"""Split the custom TTS connection into provider slots and record audio metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    word_columns = _columns("words")
    with op.batch_alter_table("words") as batch:
        if "audio_provider" not in word_columns:
            batch.add_column(sa.Column("audio_provider", sa.String(length=16), nullable=True))
        if "audio_model" not in word_columns:
            batch.add_column(sa.Column("audio_model", sa.String(length=200), nullable=True))

    # 0010 stored one connection in custom_*; route it by protocol so a full
    # Doubao agent-plan URL can never be sent through Mimo's chat contract.
    op.execute(
        "UPDATE system_audio_settings "
        "SET volc_base_url = CASE WHEN (custom_base_url LIKE '%openspeech.bytedance.com%' "
        "OR custom_base_url LIKE '%/api/v3/plan/tts/%') AND volc_base_url IS NULL "
        "THEN custom_base_url ELSE volc_base_url END, "
        "volc_api_key = CASE WHEN (custom_base_url LIKE '%openspeech.bytedance.com%' "
        "OR custom_base_url LIKE '%/api/v3/plan/tts/%') AND volc_api_key IS NULL "
        "THEN custom_api_key ELSE volc_api_key END, "
        "mimo_base_url = CASE WHEN (custom_base_url IS NOT NULL AND NOT "
        "(custom_base_url LIKE '%openspeech.bytedance.com%' "
        "OR custom_base_url LIKE '%/api/v3/plan/tts/%')) AND mimo_base_url IS NULL "
        "THEN custom_base_url ELSE mimo_base_url END, "
        "mimo_api_key = CASE WHEN (custom_base_url IS NOT NULL AND NOT "
        "(custom_base_url LIKE '%openspeech.bytedance.com%' "
        "OR custom_base_url LIKE '%/api/v3/plan/tts/%')) AND mimo_api_key IS NULL "
        "THEN custom_api_key ELSE mimo_api_key END"
    )
    op.execute("UPDATE system_audio_settings SET default_provider = 'volc'")


def downgrade() -> None:
    word_columns = _columns("words")
    with op.batch_alter_table("words") as batch:
        for name in ("audio_model", "audio_provider"):
            if name in word_columns:
                batch.drop_column(name)
