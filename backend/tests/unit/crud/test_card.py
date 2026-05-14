"""
Unit tests for CRUDCard.

Uses AsyncMock sessions — no real DB.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.card import CRUDCard
from app.models.card import Card, CardType
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def crud() -> CRUDCard:
    """Return a fresh CRUDCard instance."""
    return CRUDCard()


def _db_returning(value: object) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ── get ───────────────────────────────────────────────────────────────────────


class TestGet:
    """Tests for CRUDCard.get."""

    @pytest.mark.asyncio
    async def test_returns_card_when_found(
        self, crud: CRUDCard, debit_card: Card
    ) -> None:
        """get() returns the card when found."""
        db = _db_returning(debit_card)
        result = await crud.get(db, card_id=debit_card.id)
        assert result is debit_card

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, crud: CRUDCard) -> None:
        """get() returns None when the card is not found."""
        db = _db_returning(None)
        result = await crud.get(db, card_id=uuid.uuid4())
        assert result is None


# ── get_by_hmac ───────────────────────────────────────────────────────────────


class TestGetByHmac:
    """Tests for CRUDCard.get_by_hmac."""

    @pytest.mark.asyncio
    async def test_returns_card_for_known_hmac(
        self, crud: CRUDCard, debit_card: Card
    ) -> None:
        """get_by_hmac() returns the card when the HMAC is known."""
        db = _db_returning(debit_card)
        result = await crud.get_by_hmac(db, number_hmac=debit_card.number_hmac)
        assert result is debit_card

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_hmac(self, crud: CRUDCard) -> None:
        """get_by_hmac() returns None when the HMAC is not found."""
        db = _db_returning(None)
        result = await crud.get_by_hmac(db, number_hmac="z" * 64)
        assert result is None


# ── get_all_by_account ────────────────────────────────────────────────────────


class TestGetAllByAccount:
    """Tests for CRUDCard.get_all_by_account."""

    @pytest.mark.asyncio
    async def test_returns_cards_for_account(
        self, crud: CRUDCard, debit_card: Card, credit_card: Card
    ) -> None:
        """get_all_by_account() returns all cards for the given account."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [debit_card, credit_card]
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_all_by_account(db, account_id=debit_card.account_id)

        assert len(result) == 2
        assert debit_card in result
        assert credit_card in result

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_cards(self, crud: CRUDCard) -> None:
        """get_all_by_account() returns an empty list when the account has no cards."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_all_by_account(db, account_id=uuid.uuid4())

        assert result == []


# ── create ────────────────────────────────────────────────────────────────────


class TestCreate:
    """Tests for CRUDCard.create."""

    @pytest.mark.asyncio
    async def test_creates_card_and_returns_instance(self, crud: CRUDCard) -> None:
        """create() adds the card, flushes, refreshes and returns it."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        account_id = uuid.uuid4()
        result = await crud.create(
            db,
            account_id=account_id,
            card_type=CardType.debit,
            number_hmac="c" * 64,
            number_last4="5678",
            expiration_month=6,
            expiration_year=28,
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.account_id == account_id
        assert result.card_type == CardType.debit
        assert result.number_last4 == "5678"

    @pytest.mark.asyncio
    async def test_create_card_integrity_error_propagates(self, crud: CRUDCard) -> None:
        """create() propagates IntegrityError on duplicate number_hmac."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock(side_effect=IntegrityError(None, None, None))

        with pytest.raises(IntegrityError):
            await crud.create(
                db,
                account_id=uuid.uuid4(),
                card_type=CardType.debit,
                number_hmac="d" * 64,
                number_last4="0000",
                expiration_month=1,
                expiration_year=29,
            )
