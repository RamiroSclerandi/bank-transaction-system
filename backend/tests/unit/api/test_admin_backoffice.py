"""
Unit tests for admin backoffice endpoints.

GET /api/v1/admin/transactions                    — list all transactions (with filters)
GET /api/v1/admin/transactions/{transaction_id}   — get any transaction by ID

Uses dependency_overrides + service mock. No real DB.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from fastapi import HTTPException


def _make_transaction_mock() -> MagicMock:
    """Build a minimal Transaction mock compatible with TransactionRead."""
    tx = MagicMock(spec=Transaction)
    tx.id = uuid.uuid4()
    tx.source_card = uuid.uuid4()
    tx.origin_account = uuid.uuid4()
    tx.destination_account = "destination-123"
    tx.amount = Decimal("100.0000")
    tx.type = TransactionType.national
    tx.method = TransactionMethod.debit
    tx.status = TransactionStatus.completed
    tx.scheduled_for = None
    tx.reversal_of = None
    tx.created_at = datetime.now(UTC).replace(tzinfo=None)
    return tx


class TestAdminListTransactions:
    """Tests for GET /api/v1/admin/transactions."""

    @pytest.mark.asyncio
    async def test_list_transactions_no_filters_returns_200(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_admin_transaction_service: MagicMock,
    ) -> None:
        """Admin lists transactions without filters → 200 with list."""
        txs = [_make_transaction_mock(), _make_transaction_mock()]
        mock_api_admin_transaction_service.list_transactions_admin = AsyncMock(
            return_value=txs
        )

        response = await async_client.get("/api/v1/admin/transactions")  # type: ignore[union-attr]

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_list_transactions_with_filters_returns_200(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_admin_transaction_service: MagicMock,
    ) -> None:
        """Admin filters by status=completed → 200."""
        txs = [_make_transaction_mock()]
        mock_api_admin_transaction_service.list_transactions_admin = AsyncMock(
            return_value=txs
        )

        response = await async_client.get(  # type: ignore[union-attr]
            "/api/v1/admin/transactions?status=completed&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_list_transactions_empty_returns_200(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_admin_transaction_service: MagicMock,
    ) -> None:
        """No transactions match filters → 200 empty list."""
        mock_api_admin_transaction_service.list_transactions_admin = AsyncMock(
            return_value=[]
        )

        response = await async_client.get("/api/v1/admin/transactions")  # type: ignore[union-attr]

        assert response.status_code == 200
        assert response.json() == []


class TestAdminGetTransaction:
    """Tests for GET /api/v1/admin/transactions/{transaction_id}."""

    @pytest.mark.asyncio
    async def test_get_transaction_success_returns_200(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_admin_transaction_service: MagicMock,
    ) -> None:
        """Existing transaction → 200 with full details."""
        tx = _make_transaction_mock()
        mock_api_admin_transaction_service.get_transaction_admin = AsyncMock(
            return_value=tx
        )

        response = await async_client.get(  # type: ignore[union-attr]
            f"/api/v1/admin/transactions/{tx.id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(tx.id)

    @pytest.mark.asyncio
    async def test_get_transaction_not_found_returns_404(
        self,
        async_client: object,
        override_get_current_admin: User,
        mock_api_admin_transaction_service: MagicMock,
    ) -> None:
        """Non-existent transaction → 404."""
        mock_api_admin_transaction_service.get_transaction_admin = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Transaction not found.")
        )

        response = await async_client.get(  # type: ignore[union-attr]
            f"/api/v1/admin/transactions/{uuid.uuid4()}"
        )

        assert response.status_code == 404
