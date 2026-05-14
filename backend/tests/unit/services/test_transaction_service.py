"""
Tests the processing decision tree in isolation by mocking CRUD and SQS calls.
Coverage target: 80% of the service module (see pyproject.toml).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.account import Account
from app.models.card import Card, CardType
from app.models.transaction import (
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.schemas.card import CardInput
from app.schemas.transaction import TransactionCreate
from app.services import transaction_service

# -- Card input helpers --------------------------------------------------------

_DEBIT_CARD_INPUT = CardInput(
    number="4111-1111-1111-1111",
    expiration_month=12,
    expiration_year=30,
    cvv="123",
    card_type=CardType.debit,
)
_CREDIT_CARD_INPUT = CardInput(
    number="5500-0000-0000-0004",
    expiration_month=12,
    expiration_year=30,
    cvv="321",
    card_type=CardType.credit,
)


class TestCreateTransaction:
    """Tests for transaction_service.create_transaction."""

    @pytest.mark.asyncio
    async def test_scheduled_future_creates_scheduled_status(
        self,
        mock_crud_card: MagicMock,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """A transaction with a future scheduled_for must be saved as SCHEDULED."""
        future = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(days=1)
        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="dest-123",
            amount=Decimal("50.00"),
            type=TransactionType.national,
            scheduled_for=future,
        )
        mock_crud_tx.create = AsyncMock(
            return_value=make_transaction(TransactionStatus.scheduled)
        )

        result = await transaction_service.create_transaction(
            payload=payload, db=mock_db, current_user=customer_user
        )

        assert result.status == TransactionStatus.scheduled
        call_kwargs = mock_crud_tx.create.call_args.kwargs
        assert call_kwargs["status"] == TransactionStatus.scheduled
        assert call_kwargs["scheduled_for"] == future

    @pytest.mark.asyncio
    async def test_international_creates_pending_and_publishes_sqs(
        self,
        mock_crud_card: MagicMock,
        mock_crud_tx: MagicMock,
        mock_sqs: AsyncMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """International transactions must be saved as PENDING and published to SQS."""
        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="IBAN12345",
            amount=Decimal("200.00"),
            type=TransactionType.international,
        )
        created_tx = make_transaction(
            TransactionStatus.pending, tx_type=TransactionType.international
        )
        mock_crud_tx.create = AsyncMock(return_value=created_tx)

        result = await transaction_service.create_transaction(
            payload=payload, db=mock_db, current_user=customer_user
        )

        assert result.status == TransactionStatus.pending
        mock_sqs.assert_awaited_once_with(created_tx)

    @pytest.mark.asyncio
    async def test_national_debit_sufficient_balance_completes(
        self,
        mock_crud_card: MagicMock,
        mock_crud_account: MagicMock,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """Debit national transaction with sufficient balance must complete."""
        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="dest-account-uuid",
            amount=Decimal("100.00"),
            type=TransactionType.national,
        )
        mock_crud_tx.create = AsyncMock(
            return_value=make_transaction(TransactionStatus.completed)
        )

        result = await transaction_service.create_transaction(
            payload=payload, db=mock_db, current_user=customer_user
        )

        assert result.status == TransactionStatus.completed
        mock_crud_account.deduct_balance.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_national_debit_insufficient_balance_raises_402_and_persists(
        self,
        mock_crud_card: MagicMock,
        mock_crud_account: MagicMock,
        mock_crud_tx: MagicMock,
        customer_user: User,
        account: Account,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """
        Debit national tx with insufficient balance must raise HTTP 402.
        The FAILED transaction must still be persisted (audit trail), and
        no balance deduction must occur.
        """
        from fastapi import HTTPException

        account.balance = Decimal("10.00")
        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="dest-account-uuid",
            amount=Decimal("500.00"),
            type=TransactionType.national,
        )
        mock_crud_tx.create = AsyncMock(
            return_value=make_transaction(TransactionStatus.failed)
        )

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert exc_info.value.status_code == 402
        mock_crud_account.deduct_balance.assert_not_awaited()
        mock_crud_tx.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_national_credit_completes_without_balance_check(
        self,
        mock_crud_card_credit: MagicMock,
        mock_crud_account: MagicMock,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """Credit national transactions must complete without any balance check."""
        payload = TransactionCreate(
            card=_CREDIT_CARD_INPUT,
            destination_account="dest-account-uuid",
            amount=Decimal("9999.00"),
            type=TransactionType.national,
        )
        mock_crud_tx.create = AsyncMock(
            return_value=make_transaction(
                TransactionStatus.completed, method=TransactionMethod.credit
            )
        )

        result = await transaction_service.create_transaction(
            payload=payload, db=mock_db, current_user=customer_user
        )

        assert result.status == TransactionStatus.completed
        mock_crud_account.get_with_lock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_card_not_owned_raises_403(
        self,
        mock_crud_card: MagicMock,
        customer_user: User,
        debit_card: Card,
        mock_db: AsyncMock,
    ):
        """Using another user's card must raise HTTP 403."""
        from fastapi import HTTPException

        debit_card.account.user_id = uuid.uuid4()  # type: ignore[union-attr]  # different user
        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="dest",
            amount=Decimal("10.00"),
            type=TransactionType.national,
        )

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reversal_target_not_found_raises_404(
        self,
        mock_crud_card: MagicMock,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ):
        """Specifying a reversal_of UUID that does not exist must raise 404."""
        from fastapi import HTTPException

        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="dest",
            amount=Decimal("10.00"),
            type=TransactionType.national,
            reversal_of=uuid.uuid4(),
        )
        mock_crud_tx.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_user_account_not_found_when_creating_new_card_raises_404(
        self,
        mock_crud_card: MagicMock,
        mock_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ):
        """If the authenticated user has no account, card creation must raise 404."""
        from fastapi import HTTPException

        mock_crud_card.get_by_hmac = AsyncMock(return_value=None)
        mock_crud_card.create = AsyncMock()
        mock_crud_account.get_by_user = AsyncMock(return_value=None)

        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="dest",
            amount=Decimal("10.00"),
            type=TransactionType.national,
        )
        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_sqs_publish_failure_propagates_exception(
        self,
        mock_crud_card: MagicMock,
        mock_crud_tx: MagicMock,
        mock_sqs: AsyncMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """
        If SQS publish raises, the exception must propagate out of create_transaction.
        The DB context manager's __aexit__ (return_value=False) does not suppress it,
        which causes SQLAlchemy to rollback the implicit transaction — the same
        behaviour as in production.

        AWS relevance: a misconfigured queue URL or missing credentials would
        produce a botocore.exceptions.ClientError here, leaving no orphan
        PENDING row in the database.
        """
        payload = TransactionCreate(
            card=_DEBIT_CARD_INPUT,
            destination_account="IBAN99",
            amount=Decimal("500.00"),
            type=TransactionType.international,
        )
        created_tx = make_transaction(
            TransactionStatus.pending, tx_type=TransactionType.international
        )
        mock_crud_tx.create = AsyncMock(return_value=created_tx)
        mock_sqs.side_effect = RuntimeError("SQS unavailable")

        with pytest.raises(RuntimeError, match="SQS unavailable"):
            await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )


class TestGetTransactionForCustomer:
    """Tests for transaction_service.get_transaction_for_customer."""

    @pytest.mark.asyncio
    async def test_returns_own_transaction(
        self,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """A transaction owned by the current user is returned as-is."""
        tx = make_transaction(TransactionStatus.completed)
        tx.account.user_id = customer_user.id
        mock_crud_tx.get = AsyncMock(return_value=tx)

        result = await transaction_service.get_transaction_for_customer(
            db=mock_db, transaction_id=tx.id, current_user=customer_user
        )

        assert result is tx

    @pytest.mark.asyncio
    async def test_transaction_not_found_raises_404(
        self,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ):
        """When the transaction does not exist a 404 is raised."""
        from fastapi import HTTPException

        mock_crud_tx.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.get_transaction_for_customer(
                db=mock_db, transaction_id=uuid.uuid4(), current_user=customer_user
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_transaction_belonging_to_other_user_raises_403(
        self,
        mock_crud_tx: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """A transaction owned by a different user must raise 403, not expose data."""
        from fastapi import HTTPException

        tx = make_transaction(TransactionStatus.completed)
        tx.account.user_id = uuid.uuid4()  # different user
        mock_crud_tx.get = AsyncMock(return_value=tx)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.get_transaction_for_customer(
                db=mock_db, transaction_id=tx.id, current_user=customer_user
            )

        assert exc_info.value.status_code == 403


class TestListAccountTransactionsForCustomer:
    """Tests for transaction_service.list_account_transactions_for_customer."""

    @pytest.mark.asyncio
    async def test_returns_transactions_for_own_account(
        self,
        mock_crud_tx: MagicMock,
        mock_crud_account: MagicMock,
        customer_user: User,
        account: Account,
        mock_db: AsyncMock,
        make_transaction: Callable[..., MagicMock],
    ):
        """Own account returns the list from CRUD ordered as received."""
        tx1 = make_transaction(TransactionStatus.completed)
        tx2 = make_transaction(TransactionStatus.failed)
        mock_crud_account.get = AsyncMock(return_value=account)
        mock_crud_tx.list_by_account = AsyncMock(return_value=[tx1, tx2])

        result = await transaction_service.list_account_transactions_for_customer(
            db=mock_db,
            account_id=account.id,
            current_user=customer_user,
            limit=50,
            offset=0,
        )

        assert result == [tx1, tx2]
        mock_crud_tx.list_by_account.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_account_not_owned_raises_403(
        self,
        mock_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ):
        """Accessing another user's account must raise 403 without querying transactions."""  # noqa: E501
        from fastapi import HTTPException

        other_account = MagicMock()
        other_account.id = uuid.uuid4()
        other_account.user_id = uuid.uuid4()  # different user
        mock_crud_account.get = AsyncMock(return_value=other_account)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.list_account_transactions_for_customer(
                db=mock_db,
                account_id=other_account.id,
                current_user=customer_user,
                limit=50,
                offset=0,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_account_not_found_raises_403(
        self,
        mock_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ):
        """A non-existent account ID must raise 403 (no information leakage about ownership)."""  # noqa: E501
        from fastapi import HTTPException

        mock_crud_account.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.list_account_transactions_for_customer(
                db=mock_db,
                account_id=uuid.uuid4(),
                current_user=customer_user,
                limit=50,
                offset=0,
            )

        assert exc_info.value.status_code == 403
