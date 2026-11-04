"""Add an independently configured Seed Audio service."""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 creates the current ORM schema on fresh installs; released databases
    # still have the old shape. Support both without rewriting that migration.
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("system_audio_settings")}
    for name, length in (("seed_audio_base_url", 500), ("seed_audio_api_key", 1000),
                         ("seed_audio_model", 200), ("seed_audio_voice", 200)):
        if name not in existing:
            op.add_column("system_audio_settings", sa.Column(name, sa.String(length), nullable=True))
    with op.batch_alter_table("system_audio_settings") as batch:
        batch.drop_constraint("ck_system_audio_settings_provider", type_="check")
        batch.create_check_constraint(
            "ck_system_audio_settings_provider", "default_provider IN ('mimo','volc','seed_audio')"
        )


def downgrade() -> None:
    op.execute("UPDATE system_audio_settings SET default_provider = 'volc' WHERE default_provider = 'seed_audio'")
    with op.batch_alter_table("system_audio_settings") as batch:
        batch.drop_constraint("ck_system_audio_settings_provider", type_="check")
        batch.create_check_constraint("ck_system_audio_settings_provider", "default_provider IN ('mimo','volc')")
        batch.drop_column("seed_audio_api_key")
        batch.drop_column("seed_audio_base_url")
        batch.drop_column("seed_audio_model")
        batch.drop_column("seed_audio_voice")
