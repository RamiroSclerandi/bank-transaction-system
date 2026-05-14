"""
Unit test conftest: app factory, dependency overrides, async_client fixture.

All fixtures here are for unit tests only — no real DB or network.
"""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.deps import get_current_admin, get_current_customer, get_current_user, get_db
from app.main import app
from app.models.user import User
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_unit_db() -> AsyncMock:
    """Minimal AsyncSession mock for unit endpoint tests."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.begin = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return db


@pytest.fixture
def override_get_db(mock_unit_db: AsyncMock) -> Generator[AsyncMock, None, None]:
    """Override get_db dependency with mock session for unit tests."""

    async def _mock_get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_unit_db

    app.dependency_overrides[get_db] = _mock_get_db
    yield mock_unit_db
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def override_get_current_user(customer_user: User) -> Generator[User, None, None]:
    """Override get_current_user to return the customer_user fixture."""
    app.dependency_overrides[get_current_user] = lambda: customer_user
    yield customer_user
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def override_get_current_customer(customer_user: User) -> Generator[User, None, None]:
    """Override get_current_customer to return the customer_user fixture."""
    app.dependency_overrides[get_current_customer] = lambda: customer_user
    yield customer_user
    app.dependency_overrides.pop(get_current_customer, None)


@pytest.fixture
def override_get_current_admin(admin_user: User) -> Generator[User, None, None]:
    """Override get_current_admin to return the admin_user fixture."""
    app.dependency_overrides[get_current_admin] = lambda: admin_user
    yield admin_user
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.fixture
async def async_client(override_get_db: AsyncMock) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with mocked DB for unit endpoint tests."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


# ── deps.py patch fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_deps_crud_user_session() -> Generator[MagicMock, None, None]:
    """Patch crud_user_session inside app.deps."""
    with patch("app.deps.crud_user_session") as mock:
        yield mock


@pytest.fixture
def mock_deps_crud_user() -> Generator[MagicMock, None, None]:
    """Patch crud_user inside app.deps."""
    with patch("app.deps.crud_user") as mock:
        yield mock


@pytest.fixture
def mock_deps_hash_token() -> Generator[MagicMock, None, None]:
    """Patch hash_session_token inside app.deps."""
    with patch("app.deps.hash_session_token", return_value="deadbeef") as mock:
        yield mock


# ── Unit-level service patch fixtures for API tests ──


@pytest.fixture
def mock_api_auth_service() -> Generator[MagicMock, None, None]:
    """Patch auth_service module as used in auth endpoints."""
    with patch("app.api.api_v1.endpoints.auth.auth_service") as mock:
        yield mock


@pytest.fixture
def mock_api_user_service() -> Generator[MagicMock, None, None]:
    """Patch user_service module as used in auth and account endpoints."""
    with patch("app.api.api_v1.endpoints.auth.user_service") as mock:
        yield mock


@pytest.fixture
def mock_api_transaction_service() -> Generator[MagicMock, None, None]:
    """Patch transaction_service in transactions endpoints."""
    with patch("app.api.api_v1.endpoints.transactions.transaction_service") as mock:
        yield mock


@pytest.fixture
def mock_api_admin_transaction_service() -> Generator[MagicMock, None, None]:
    """Patch transaction_service in admin_backoffice endpoints."""
    with patch("app.api.api_v1.endpoints.admin_backoffice.transaction_service") as mock:
        yield mock


@pytest.fixture
def mock_api_crud_account() -> Generator[MagicMock, None, None]:
    """Patch crud_account in accounts endpoints."""
    with patch("app.api.api_v1.endpoints.accounts.crud_account") as mock:
        yield mock


@pytest.fixture
def mock_api_crud_user() -> Generator[MagicMock, None, None]:
    """Patch crud_user in accounts endpoints."""
    with patch("app.api.api_v1.endpoints.accounts.crud_user") as mock:
        yield mock


@pytest.fixture
def mock_api_accounts_user_service() -> Generator[MagicMock, None, None]:
    """Patch user_service in accounts endpoints."""
    with patch("app.api.api_v1.endpoints.accounts.user_service") as mock:
        yield mock
