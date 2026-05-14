"""
Unit tests for auth endpoints.

POST /api/v1/auth/register — customer register: 201 success, 409 duplicate
POST /api/v1/auth/login    — customer login: 200 success, 401 wrong creds
POST /api/v1/auth/logout   — customer logout: 204 success, 401 unauthenticated

Uses dependency_overrides to mock services. No real DB.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.audit_log import UserSession
from app.models.user import User
from fastapi import HTTPException


class TestCustomerRegister:
    """Tests for POST /api/v1/auth/register."""

    @pytest.mark.asyncio
    async def test_register_success_returns_201(
        self,
        async_client: object,
        mock_api_user_service: MagicMock,
        customer_user: User,
        account: object,
    ) -> None:
        """Valid registration payload → 201 with user and account data."""
        mock_api_user_service.register_customer = AsyncMock(
            return_value=(customer_user, account)
        )

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/auth/register",
            json={
                "name": "Test Customer",
                "email": "customer@example.com",
                "password": "securepass",
                "national_id": 12345678,
                "phone": 600000000,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert "user" in data
        assert "account" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_returns_409(
        self,
        async_client: object,
        mock_api_user_service: MagicMock,
    ) -> None:
        """Duplicate email → service raises 409 → response is 409."""
        mock_api_user_service.register_customer = AsyncMock(
            side_effect=HTTPException(
                status_code=409, detail="Email already registered."
            )
        )

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/auth/register",
            json={
                "name": "Dup",
                "email": "dup@example.com",
                "password": "securepass",
                "national_id": 11111111,
                "phone": 600000001,
            },
        )

        assert response.status_code == 409


class TestCustomerLogin:
    """Tests for POST /api/v1/auth/login."""

    @pytest.mark.asyncio
    async def test_login_success_returns_200(
        self,
        async_client: object,
        mock_api_auth_service: MagicMock,
    ) -> None:
        """Valid credentials → 200 with session_token and expires_at."""
        session = MagicMock(spec=UserSession)
        session.expires_at = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(
            minutes=15
        )
        mock_api_auth_service.login = AsyncMock(return_value=(session, "raw-token"))

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/auth/login",
            json={"email": "customer@example.com", "password": "pass"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["session_token"] == "raw-token"  # noqa: S105

    @pytest.mark.asyncio
    async def test_login_wrong_credentials_returns_401(
        self,
        async_client: object,
        mock_api_auth_service: MagicMock,
    ) -> None:
        """Wrong password → service raises 401 → response is 401."""
        mock_api_auth_service.login = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Invalid credentials.")
        )

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/auth/login",
            json={"email": "customer@example.com", "password": "wrong"},
        )

        assert response.status_code == 401


class TestCustomerLogout:
    """Tests for POST /api/v1/auth/logout."""

    @pytest.mark.asyncio
    async def test_logout_success_returns_204(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_auth_service: MagicMock,
    ) -> None:
        """Authenticated customer logout → 204 No Content."""
        mock_api_auth_service.logout = AsyncMock()

        response = await async_client.post("/api/v1/auth/logout")  # type: ignore[union-attr]

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_logout_unauthenticated_returns_401(
        self,
        async_client: object,
    ) -> None:
        """No auth token → 401 (HTTPBearer auto_error=True)."""
        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/auth/logout",
            headers={"Authorization": ""},
        )

        assert response.status_code in (401, 403)
