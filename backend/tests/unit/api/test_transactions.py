"""
Unit tests for customer transaction endpoints.

POST /api/v1/transactions                              — create transaction
GET  /api/v1/transactions/{transaction_id}             — get own transaction
GET  /api/v1/transactions/accounts/{account_id}/transactions — list account txs

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


class TestCreateTransaction:
    """Tests for POST /api/v1/transactions."""

    @pytest.mark.asyncio
    async def test_create_transaction_success_returns_201(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_transaction_service: MagicMock,
    ) -> None:
        """Valid payload → 201 with transaction data."""
        tx = _make_transaction_mock()
        mock_api_transaction_service.create_transaction = AsyncMock(return_value=tx)

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/transactions",
            json={
                "card": {
                    "number": "4111-1111-1111-1111",
                    "card_type": "debit",
                    "expiration_month": 12,
                    "expiration_year": 30,
                    "cvv": "123",
                },
                "destination_account": "destination-123",
                "amount": "100.0000",
                "type": "national",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_create_transaction_insufficient_funds_returns_422(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_transaction_service: MagicMock,
    ) -> None:
        """Service raises 422 on insufficient balance → 422."""
        mock_api_transaction_service.create_transaction = AsyncMock(
            side_effect=HTTPException(status_code=422, detail="Insufficient balance.")
        )

        response = await async_client.post(  # type: ignore[union-attr]
            "/api/v1/transactions",
            json={
                "card": {
                    "number": "4111-1111-1111-1111",
                    "card_type": "debit",
                    "expiration_month": 12,
                    "expiration_year": 30,
                    "cvv": "123",
                },
                "destination_account": "dest",
                "amount": "99999.0000",
                "type": "national",
            },
        )

        assert response.status_code == 422


class TestGetTransaction:
    """Tests for GET /api/v1/transactions/{transaction_id}."""

    @pytest.mark.asyncio
    async def test_get_transaction_success_returns_200(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_transaction_service: MagicMock,
    ) -> None:
        """Existing owned transaction → 200."""
        tx = _make_transaction_mock()
        mock_api_transaction_service.get_transaction_for_customer = AsyncMock(
            return_value=tx
        )

        response = await async_client.get(  # type: ignore[union-attr]
            f"/api/v1/transactions/{tx.id}",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(tx.id)

    @pytest.mark.asyncio
    async def test_get_transaction_not_found_returns_404(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_transaction_service: MagicMock,
    ) -> None:
        """Non-existent transaction → 404."""
        mock_api_transaction_service.get_transaction_for_customer = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Transaction not found.")
        )

        response = await async_client.get(  # type: ignore[union-attr]
            f"/api/v1/transactions/{uuid.uuid4()}",
        )

        assert response.status_code == 404


class TestListAccountTransactions:
    """Tests for GET /api/v1/transactions/accounts/{account_id}/transactions."""

    @pytest.mark.asyncio
    async def test_list_transactions_success_returns_200(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_transaction_service: MagicMock,
    ) -> None:
        """Valid account → 200 with list of transactions."""
        txs = [_make_transaction_mock(), _make_transaction_mock()]
        mock_api_transaction_service.list_account_transactions_for_customer = AsyncMock(
            return_value=txs
        )

        account_id = uuid.uuid4()
        response = await async_client.get(  # type: ignore[union-attr]
            f"/api/v1/transactions/accounts/{account_id}/transactions",
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    @pytest.mark.asyncio
    async def test_list_transactions_unauthorized_account_returns_403(
        self,
        async_client: object,
        override_get_current_customer: User,
        mock_api_transaction_service: MagicMock,
    ) -> None:
        """Account belongs to another user → 403."""
        mock_api_transaction_service.list_account_transactions_for_customer = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not your account.")
        )

        response = await async_client.get(  # type: ignore[union-attr]
            f"/api/v1/transactions/accounts/{uuid.uuid4()}/transactions",
        )

        assert response.status_code == 403
