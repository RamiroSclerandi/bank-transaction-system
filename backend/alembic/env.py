"""
Alembic async migration environment for PostgreSQL + asyncpg.
Reads DATABASE_URL from app settings and runs migrations using an async
SQLAlchemy engine so the connection string does not need to be duplicated
in alembic.ini.
"""

import asyncio
import sys
from pathlib import Path

# Ensure the project root (backend/) is on sys.path so `import app` works
# regardless of where the alembic command is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logging.config import fileConfig

from alembic import context
from app.core.config import settings
from app.db.base import Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

# Override sqlalchemy.url with the value from app settings (env-based)
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    """
    Run migrations in 'offline' mode (generates SQL without a live connection).
    Useful for generating SQL scripts for review or execution by a DBA.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection):
    """
    Execute migrations against an open synchronous connection.

    Args:
    ----
        connection: A synchronous SQLAlchemy connection provided by the
            async bridge.

    """
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    """
    Create an async engine and run migrations via run_sync.
    Uses NullPool so no connections are held open after migrations complete.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    """Entry point for online migrations (live DB connection)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
