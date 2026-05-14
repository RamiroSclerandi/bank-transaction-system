"""
Unit tests for CRUDTransaction.

Covers get_due_ids (pre-existing) plus create, get, list_by_account,
list_filtered, and update_status.

All tests use AsyncMock sessions — no real DB.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.transaction import CRUDTransaction
from app.models.transaction import (
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.schemas.transaction import TransactionListFilters


@pytest.fixture
def crud() -> CRUDTransaction:
    """Return a fresh CRUDTransaction instance."""
    return CRUDTransaction()


# ── get_due_ids (pre-existing tests kept) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_get_due_ids_returns_qualifying_uuids() -> None:
    """get_due_ids returns IDs matching status=scheduled and scheduled_for <= now."""
    due_id = uuid.uuid4()
    db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [due_id]
    db.execute = AsyncMock(return_value=mock_result)

    crud = CRUDTransaction()
    result = await crud.get_due_ids(db)

    assert result == [due_id]
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_due_ids_returns_empty_list_when_none_qualify() -> None:
    """get_due_ids returns [] when no transactions qualify."""
    db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    crud = CRUDTransaction()
    result = await crud.get_due_ids(db)

    assert result == []
    db.execute.assert_awaited_once()


# ── get ───────────────────────────────────────────────────────────────────────


class TestGet:
    """Tests for CRUDTransaction.get."""

    @pytest.mark.asyncio
    async def test_returns_transaction_when_found(
        self, crud: CRUDTransaction, make_transaction: object
    ) -> None:
        """get() returns the Transaction when it exists."""
        tx = make_transaction(TransactionStatus.completed)  # type: ignore[operator]
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = tx
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get(db, transaction_id=tx.id)
        assert result is tx

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, crud: CRUDTransaction) -> None:
        """get() returns None when transaction does not exist."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get(db, transaction_id=uuid.uuid4())
        assert result is None


# ── create ────────────────────────────────────────────────────────────────────


class TestCreate:
    """Tests for CRUDTransaction.create."""

    @pytest.mark.asyncio
    async def test_create_returns_new_transaction(self, crud: CRUDTransaction) -> None:
        """create() adds a Transaction, flushes, refreshes, and returns it."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        source_card = uuid.uuid4()
        origin_account = uuid.uuid4()

        result = await crud.create(
            db,
            source_card=source_card,
            origin_account=origin_account,
            destination_account="dest-123",
            amount=Decimal("100.0000"),
            transaction_type=TransactionType.national,
            method=TransactionMethod.debit,
            status=TransactionStatus.pending,
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.source_card == source_card
        assert result.origin_account == origin_account
        assert result.amount == Decimal("100.0000")
        assert result.status == TransactionStatus.pending


# ── list_by_account ───────────────────────────────────────────────────────────


class TestListByAccount:
    """Tests for CRUDTransaction.list_by_account."""

    @pytest.mark.asyncio
    async def test_returns_transactions_for_account(
        self, crud: CRUDTransaction, make_transaction: object
    ) -> None:
        """list_by_account() returns all transactions for the given account."""
        tx1 = make_transaction(TransactionStatus.completed)  # type: ignore[operator]
        tx2 = make_transaction(TransactionStatus.pending)  # type: ignore[operator]
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [tx1, tx2]
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.list_by_account(db, account_id=uuid.uuid4())

        assert len(result) == 2
        assert tx1 in result
        assert tx2 in result

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_transactions(
        self, crud: CRUDTransaction
    ) -> None:
        """list_by_account() returns [] when account has no transactions."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.list_by_account(db, account_id=uuid.uuid4())

        assert result == []


# ── list_filtered ─────────────────────────────────────────────────────────────


class TestListFiltered:
    """Tests for CRUDTransaction.list_filtered."""

    @pytest.mark.asyncio
    async def test_returns_filtered_list(
        self, crud: CRUDTransaction, make_transaction: object
    ) -> None:
        """list_filtered() returns transactions matching the filters."""
        tx = make_transaction(TransactionStatus.completed)  # type: ignore[operator]
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [tx]
        db.execute = AsyncMock(return_value=result_mock)

        filters = TransactionListFilters(limit=10, offset=0)
        result = await crud.list_filtered(db, filters=filters)

        assert len(result) == 1
        assert result[0] is tx

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self, crud: CRUDTransaction) -> None:
        """list_filtered() returns [] when no transactions match the filters."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        filters = TransactionListFilters(
            limit=10, offset=0, status=TransactionStatus.completed
        )
        result = await crud.list_filtered(db, filters=filters)

        assert result == []


# ── update_status ─────────────────────────────────────────────────────────────


class TestUpdateStatus:
    """Tests for CRUDTransaction.update_status."""

    @pytest.mark.asyncio
    async def test_returns_true_when_row_updated(self, crud: CRUDTransaction) -> None:
        """update_status returns True when rowcount > 0."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 1
        db.execute = AsyncMock(return_value=result_mock)

        updated = await crud.update_status(
            db,
            transaction_id=uuid.uuid4(),
            new_status=TransactionStatus.completed,
            expected_current_status=TransactionStatus.pending,
        )

        assert updated is True

    @pytest.mark.asyncio
    async def test_returns_false_when_condition_not_met(
        self, crud: CRUDTransaction
    ) -> None:
        """update_status returns False when rowcount == 0 (optimistic lock miss)."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.rowcount = 0
        db.execute = AsyncMock(return_value=result_mock)

        updated = await crud.update_status(
            db,
            transaction_id=uuid.uuid4(),
            new_status=TransactionStatus.completed,
            expected_current_status=TransactionStatus.scheduled,
        )

        assert updated is False
