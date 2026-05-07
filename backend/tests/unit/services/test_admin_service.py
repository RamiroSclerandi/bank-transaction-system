"""
Tests for admin-facing transaction helpers in transaction_service.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.transaction import Transaction
from app.schemas.transaction import TransactionListFilters
from app.services import transaction_service
from fastapi import HTTPException


# TestGetTransactionAdmin
class TestGetTransactionAdmin:
    """Tests for transaction_service.get_transaction_admin."""

    @pytest.mark.asyncio
    @patch("app.services.transaction_service.crud_transaction")
    async def test_returns_transaction_when_found(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """When the CRUD layer finds the transaction it is returned as-is."""
        tx = MagicMock(spec=Transaction)
        tx.id = uuid.uuid4()
        mock_crud_tx.get = AsyncMock(return_value=tx)

        result = await transaction_service.get_transaction_admin(
            db=mock_db, transaction_id=tx.id
        )

        assert result is tx

    @pytest.mark.asyncio
    @patch("app.services.transaction_service.crud_transaction")
    async def test_raises_404_when_not_found(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """When the CRUD layer returns None a 404 must be raised."""
        mock_crud_tx.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.get_transaction_admin(
                db=mock_db, transaction_id=uuid.uuid4()
            )

        assert exc_info.value.status_code == 404


# TestListTransactionsAdmin
class TestListTransactionsAdmin:
    """Tests for transaction_service.list_transactions_admin."""

    @pytest.mark.asyncio
    @patch("app.services.transaction_service.crud_transaction")
    async def test_returns_list_from_crud(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """list_transactions_admin must delegate to crud and return unchanged result."""
        tx1 = MagicMock(spec=Transaction)
        tx2 = MagicMock(spec=Transaction)
        filters = TransactionListFilters(limit=10, offset=0)
        mock_crud_tx.list_filtered = AsyncMock(return_value=[tx1, tx2])

        result = await transaction_service.list_transactions_admin(
            db=mock_db, filters=filters
        )

        assert result == [tx1, tx2]
        mock_crud_tx.list_filtered.assert_awaited_once_with(mock_db, filters=filters)

    @pytest.mark.asyncio
    @patch("app.services.transaction_service.crud_transaction")
    async def test_returns_empty_list_when_no_matches(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """list_transactions_admin returns an empty list when no transactions match."""
        filters = TransactionListFilters(limit=10, offset=0)
        mock_crud_tx.list_filtered = AsyncMock(return_value=[])

        result = await transaction_service.list_transactions_admin(
            db=mock_db, filters=filters
        )

        assert result == []
        mock_crud_tx.list_filtered.assert_awaited_once_with(mock_db, filters=filters)
