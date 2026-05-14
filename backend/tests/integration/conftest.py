"""
Integration test conftest.

Spins up a real Postgres container via testcontainers, applies Alembic migrations,
and provides session-scoped async engine + function-scoped rollback sessions.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from app.deps import get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Spin up a Postgres container for the whole test session."""
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def db_url(postgres_container: PostgresContainer) -> str:
    """Return asyncpg-compatible DATABASE_URL from the container."""
    sync_url: str = postgres_container.get_connection_url()
    # testcontainers returns postgresql+psycopg2://..., replace with asyncpg driver
    return sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )


@pytest.fixture(scope="session")
def apply_migrations(postgres_container: PostgresContainer, db_url: str) -> None:
    """Apply Alembic migrations once for the whole test session."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    alembic_cfg = AlembicConfig(os.path.join(backend_dir, "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    alembic_command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session")
def async_engine(db_url: str, apply_migrations: Any):
    """Session-scoped async engine pointing at the test container."""
    engine = create_async_engine(db_url, echo=False, future=True)
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture(scope="session")
def async_session_factory(async_engine: Any) -> async_sessionmaker:
    """Session-scoped sessionmaker bound to test engine."""
    return async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
async def db_session(
    async_session_factory: async_sessionmaker,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Function-scoped async session with rollback after each test.
    Uses a nested transaction + savepoint for clean isolation.
    """
    async with async_session_factory() as session:
        await session.begin()
        yield session
        await session.rollback()


@pytest.fixture
async def async_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Function-scoped httpx client connected to the real test DB.
    Overrides get_db to yield the rollback-protected db_session.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def committed_async_client(
    async_session_factory: async_sessionmaker,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Function-scoped httpx client with a COMMITTING session for tests that need
    real DB visibility across concurrent requests (e.g. atomicity tests).
    Caller is responsible for cleaning up any committed data.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)
