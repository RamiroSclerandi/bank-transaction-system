"""
Unit tests for account endpoints.

POST /api/v1/accounts/add-balance   — add balance to own account
POST /api/v1/admin/accounts         — admin creates account for a user

Uses dependency_overrides + service/CRUD mocks. No real DB.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.account import Account
from app.models.user import User


class TestAddBalance:
    """Tests for POST /api/v1/accounts/add-balance."""

    @pytest.mark.asyncio
    async def test_add_balance_success_returns_200(
        self,
        async_client: object,
        override_get_current_user: User,
        mock_api_crud_account: MagicMock,
        account: Account,
    ) -> None:
        """Authenticated user adds balance → 200 with updated account."""
        mock_api_crud_account.get_by_user = AsyncMock(return_value=account)
        mock_api_crud_account.get_with_lock = AsyncMock(return_value=account)
        mock_api_crud_account.add_balance = AsyncMock()

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/accounts/add-balance",
            json={"amount": "100.0000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "balance" in data

    @pytest.mark.asyncio
    async def test_add_balance_account_not_found_returns_404(
        self,
        async_client: object,
        override_get_current_user: User,
        mock_api_crud_account: MagicMock,
    ) -> None:
        """User has no account → 404."""
        mock_api_crud_account.get_by_user = AsyncMock(return_value=None)

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/accounts/add-balance",
            json={"amount": "50.0000"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_add_balance_negative_amount_returns_422(
        self,
        async_client: object,
        override_get_current_user: User,
    ) -> None:
        """Negative amount fails Pydantic validation → 422."""
        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/accounts/add-balance",
            json={"amount": "-10.0000"},
        )

        assert response.status_code == 422


class TestAdminCreateAccount:
    """Tests for POST /api/v1/admin/accounts."""

    @pytest.mark.asyncio
    async def test_admin_create_account_success_returns_201(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_crud_account: MagicMock,
        mock_api_crud_user: MagicMock,
        customer_user: User,
        account: Account,
    ) -> None:
        """Admin creates account for existing user → 201."""
        mock_api_crud_user.get = AsyncMock(return_value=customer_user)
        mock_api_crud_account.get_by_user = AsyncMock(return_value=None)
        mock_api_crud_account.create = AsyncMock(return_value=account)

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/admin/accounts",
            json={"user_id": str(customer_user.id)},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == str(customer_user.id)

    @pytest.mark.asyncio
    async def test_admin_create_account_user_not_found_returns_404(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_crud_account: MagicMock,
        mock_api_crud_user: MagicMock,
    ) -> None:
        """Target user does not exist → 404."""
        mock_api_crud_user.get = AsyncMock(return_value=None)

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/admin/accounts",
            json={"user_id": str(uuid.uuid4())},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_create_account_already_exists_returns_409(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_crud_account: MagicMock,
        mock_api_crud_user: MagicMock,
        customer_user: User,
        account: Account,
    ) -> None:
        """User already has an account → 409."""
        mock_api_crud_user.get = AsyncMock(return_value=customer_user)
        mock_api_crud_account.get_by_user = AsyncMock(return_value=account)

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/admin/accounts",
            json={"user_id": str(customer_user.id)},
        )

        assert response.status_code == 409
