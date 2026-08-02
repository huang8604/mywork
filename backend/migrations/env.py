from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.database import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # Alembic's SQLite batch mode rebuilds a table by dropping and
            # renaming it. Foreign-key enforcement must be disabled while that
            # happens or ON DELETE actions can remove rows from child tables.
            connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
            connection.exec_driver_sql("PRAGMA journal_mode = WAL")
            connection.exec_driver_sql("PRAGMA busy_timeout = 5000")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            connection.commit()
            if violations:
                raise RuntimeError(f"foreign key violations after migration: {violations}")
            connection.exec_driver_sql("PRAGMA foreign_keys = ON")
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
