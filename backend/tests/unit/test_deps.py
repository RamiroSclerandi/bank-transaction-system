"""
Unit tests for app.deps security dependencies.

Covers: valid session, expired session, IP mismatch, role checks.
Uses mock_db and make_session fixtures from root conftest.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.deps import get_current_admin, get_current_customer, get_current_user
from app.models.user import User
from fastapi import BackgroundTasks, HTTPException


def _make_credentials(token: str = "raw-token") -> MagicMock:  # noqa: S107
    creds = MagicMock()
    creds.credentials = token
    return creds


def _make_session(
    user_id: uuid.UUID,
    expires_at: datetime | None = None,
    ip_address: str = "1.2.3.4",
) -> MagicMock:
    sess = MagicMock()
    sess.user_id = user_id
    sess.token_hash = "deadbeef"  # noqa: S105
    sess.ip_address = ip_address
    sess.expires_at = expires_at or datetime.now(tz=UTC).replace(
        tzinfo=None
    ) + timedelta(hours=1)
    return sess


# ── get_current_user ──────────────────────────────────────────────────────────


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_valid_session_returns_user(
        self,
        mock_db: AsyncMock,
        customer_user: User,
        mock_deps_crud_user_session: MagicMock,
        mock_deps_crud_user: MagicMock,
        mock_deps_hash_token: MagicMock,
    ) -> None:
        """Valid token + valid session → returns User object."""
        session = _make_session(user_id=customer_user.id)
        mock_deps_crud_user_session.get_by_token_hash = AsyncMock(return_value=session)
        mock_deps_crud_user.get = AsyncMock(return_value=customer_user)

        result = await get_current_user(
            credentials=_make_credentials(),
            db=mock_db,
            background_tasks=BackgroundTasks(),
        )

        assert result is customer_user

    @pytest.mark.asyncio
    async def test_session_not_found_raises_401(
        self,
        mock_db: AsyncMock,
        mock_deps_crud_user_session: MagicMock,
        mock_deps_hash_token: MagicMock,
    ) -> None:
        """No session in DB → raises 401."""
        mock_deps_crud_user_session.get_by_token_hash = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                credentials=_make_credentials(),
                db=mock_db,
                background_tasks=BackgroundTasks(),
            )

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_session_raises_401(
        self,
        mock_db: AsyncMock,
        customer_user: User,
        mock_deps_crud_user_session: MagicMock,
        mock_deps_hash_token: MagicMock,
    ) -> None:
        """Expired session → raises 401 and schedules background cleanup."""
        expired_time = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(hours=1)
        session = _make_session(user_id=customer_user.id, expires_at=expired_time)
        mock_deps_crud_user_session.get_by_token_hash = AsyncMock(return_value=session)

        bg = BackgroundTasks()
        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                credentials=_make_credentials(),
                db=mock_db,
                background_tasks=bg,
            )

        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(
        self,
        mock_db: AsyncMock,
        customer_user: User,
        mock_deps_crud_user_session: MagicMock,
        mock_deps_crud_user: MagicMock,
        mock_deps_hash_token: MagicMock,
    ) -> None:
        """Session valid but user row missing → raises 401."""
        session = _make_session(user_id=customer_user.id)
        mock_deps_crud_user_session.get_by_token_hash = AsyncMock(return_value=session)
        mock_deps_crud_user.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc:
            await get_current_user(
                credentials=_make_credentials(),
                db=mock_db,
                background_tasks=BackgroundTasks(),
            )

        assert exc.value.status_code == 401


# ── get_current_admin ─────────────────────────────────────────────────────────


class TestGetCurrentAdmin:
    """Tests for get_current_admin dependency."""

    @pytest.mark.asyncio
    async def test_admin_with_no_registered_ip_allowed(
        self,
        admin_user: User,
    ) -> None:
        """Admin with no registered_ip — any IP is accepted."""
        admin_user.registered_ip = None
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "10.0.0.1"

        result = await get_current_admin(user=admin_user, request=request)

        assert result is admin_user

    @pytest.mark.asyncio
    async def test_non_admin_raises_401(
        self,
        customer_user: User,
    ) -> None:
        """Customer trying admin dep → 401."""
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "1.2.3.4"

        with pytest.raises(HTTPException) as exc:
            await get_current_admin(user=customer_user, request=request)

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_ip_mismatch_raises_403(
        self,
        admin_user: User,
    ) -> None:
        """Admin registered_ip set but request from different IP → 403."""
        admin_user.registered_ip = "1.2.3.4"
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "9.9.9.9"

        with pytest.raises(HTTPException) as exc:
            await get_current_admin(user=admin_user, request=request)

        assert exc.value.status_code == 403


# ── get_current_customer ──────────────────────────────────────────────────────


class TestGetCurrentCustomer:
    """Tests for get_current_customer dependency."""

    @pytest.mark.asyncio
    async def test_customer_user_passes(
        self,
        customer_user: User,
    ) -> None:
        """Customer role → returns the user unchanged."""
        result = await get_current_customer(user=customer_user)
        assert result is customer_user

    @pytest.mark.asyncio
    async def test_admin_user_raises_401(
        self,
        admin_user: User,
    ) -> None:
        """Admin trying customer dep → 401."""
        with pytest.raises(HTTPException) as exc:
            await get_current_customer(user=admin_user)

        assert exc.value.status_code == 401
