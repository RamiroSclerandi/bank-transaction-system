"""
Unit tests for CRUDAccount.

Uses AsyncMock sessions — no real DB. Tests verify delegate calls and return paths.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.account import CRUDAccount
from app.models.account import Account


@pytest.fixture
def crud() -> CRUDAccount:
    """Return a fresh CRUDAccount instance."""
    return CRUDAccount()


@pytest.fixture
def mock_account() -> Account:
    """Return a minimal Account instance."""
    acc = Account(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        balance=Decimal("500.0000"),
    )
    return acc


# ── get ───────────────────────────────────────────────────────────────────────


class TestGet:
    """Tests for CRUDAccount.get."""

    @pytest.mark.asyncio
    async def test_get_returns_account_when_found(
        self, crud: CRUDAccount, mock_account: Account
    ) -> None:
        """get() returns the Account when the DB has a match."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_account
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get(db, account_id=mock_account.id)

        assert result is mock_account
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(self, crud: CRUDAccount) -> None:
        """get() returns None when no account matches."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get(db, account_id=uuid.uuid4())

        assert result is None


# ── get_by_user ───────────────────────────────────────────────────────────────


class TestGetByUser:
    """Tests for CRUDAccount.get_by_user."""

    @pytest.mark.asyncio
    async def test_returns_account_for_existing_user(
        self, crud: CRUDAccount, mock_account: Account
    ) -> None:
        """get_by_user() returns the account owned by the user."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_account
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_by_user(db, user_id=mock_account.user_id)

        assert result is mock_account

    @pytest.mark.asyncio
    async def test_returns_none_for_user_without_account(
        self, crud: CRUDAccount
    ) -> None:
        """get_by_user() returns None when user has no account."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_by_user(db, user_id=uuid.uuid4())

        assert result is None


# ── get_with_lock ─────────────────────────────────────────────────────────────


class TestGetWithLock:
    """Tests for CRUDAccount.get_with_lock."""

    @pytest.mark.asyncio
    async def test_returns_account(
        self, crud: CRUDAccount, mock_account: Account
    ) -> None:
        """get_with_lock() returns the account when row exists."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_account
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_with_lock(db, account_id=mock_account.id)

        assert result is mock_account

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, crud: CRUDAccount) -> None:
        """get_with_lock() returns None when account does not exist."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_with_lock(db, account_id=uuid.uuid4())

        assert result is None


# ── create ────────────────────────────────────────────────────────────────────


class TestCreate:
    """Tests for CRUDAccount.create."""

    @pytest.mark.asyncio
    async def test_create_returns_new_account(
        self, crud: CRUDAccount, mock_account: Account
    ) -> None:
        """create() flushes, refreshes and returns a new Account."""
        db = AsyncMock()
        db.add = MagicMock()

        async def _refresh(obj: Account) -> None:
            obj.id = mock_account.id

        db.flush = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh)

        result = await crud.create(db, user_id=mock_account.user_id)

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.user_id == mock_account.user_id
        assert result.balance == Decimal("0.0000")


# ── add_balance / deduct_balance ──────────────────────────────────────────────


class TestBalanceOperations:
    """Tests for add_balance and deduct_balance."""

    @pytest.mark.asyncio
    async def test_deduct_balance_reduces_amount(
        self, crud: CRUDAccount, mock_account: Account
    ) -> None:
        """deduct_balance() subtracts the amount from account.balance."""
        db = AsyncMock()
        db.add = MagicMock()
        initial = mock_account.balance

        await crud.deduct_balance(db, account=mock_account, amount=Decimal("100.0000"))

        assert mock_account.balance == initial - Decimal("100.0000")
        db.add.assert_called_once_with(mock_account)

    @pytest.mark.asyncio
    async def test_add_balance_increases_amount(
        self, crud: CRUDAccount, mock_account: Account
    ) -> None:
        """add_balance() adds the amount to account.balance."""
        db = AsyncMock()
        db.add = MagicMock()
        initial = mock_account.balance

        await crud.add_balance(db, account=mock_account, amount=Decimal("250.0000"))

        assert mock_account.balance == initial + Decimal("250.0000")
        db.add.assert_called_once_with(mock_account)
