"""Alembic environment. The database URL comes from the Alembic config when set
(`scout db-setup`, tests), otherwise from DATABASE_URL via the app settings."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import scout_ai.db.models  # noqa: F401  (registers every table on Base.metadata)
from scout_ai.config import get_settings
from scout_ai.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
# SQLite cannot ALTER most things in place; batch mode recreates the table instead.
render_as_batch = url.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=render_as_batch,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=render_as_batch,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
