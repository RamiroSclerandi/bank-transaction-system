"""Tests the processing decision tree in isolation by mocking CRUD and SQS calls.
Coverage target: 80% of the service module (see pyproject.toml)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.account import Account
from app.models.card import Card
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.schemas.transaction import TransactionCreate, WebhookUpdate
from app.services import transaction_service


def _make_transaction(
    status: TransactionStatus,
    method: TransactionMethod = TransactionMethod.debit,
    tx_type: TransactionType = TransactionType.national,
) -> Transaction:
    """Build a minimal Transaction ORM object for testing."""
    tx = MagicMock(spec=Transaction)
    tx.id = uuid.uuid4()
    tx.status = status
    tx.method = method
    tx.type = tx_type
    tx.origin_account = uuid.uuid4()
    tx.source_card = uuid.uuid4()
    tx.destination_account = "dest-account-123"
    tx.amount = Decimal("100.00")
    tx.account = MagicMock()
    tx.account.user_id = uuid.uuid4()
    return tx


class TestCreateTransaction:
    """Tests for transaction_service.create_transaction."""

    @pytest.mark.asyncio
    async def test_scheduled_future_creates_scheduled_status(
        self,
        customer_user: User,
        debit_card: Card,
        mock_db: AsyncMock,
    ) -> None:
        """A transaction with a future scheduled_for must be saved as SCHEDULED."""
        future = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(days=1)
        payload = TransactionCreate(
            source_card=debit_card.id,
            destination_account="dest-123",
            amount=Decimal("50.00"),
            type=TransactionType.national,
            scheduled_for=future,
        )
        created_tx = _make_transaction(TransactionStatus.scheduled)

        with (
            patch("app.services.transaction_service.crud_card") as mock_crud_card,
            patch("app.services.transaction_service.crud_transaction") as mock_crud_tx,
        ):
            mock_crud_card.get = AsyncMock(return_value=debit_card)
            mock_crud_tx.create = AsyncMock(return_value=created_tx)

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
        customer_user: User,
        debit_card: Card,
        mock_db: AsyncMock,
    ) -> None:
        """International transactions must be saved as PENDING and published to SQS."""
        payload = TransactionCreate(
            source_card=debit_card.id,
            destination_account="IBAN12345",
            amount=Decimal("200.00"),
            type=TransactionType.international,
        )
        created_tx = _make_transaction(
            TransactionStatus.pending, tx_type=TransactionType.international
        )

        with (
            patch("app.services.transaction_service.crud_card") as mock_crud_card,
            patch("app.services.transaction_service.crud_transaction") as mock_crud_tx,
            patch(
                "app.services.transaction_service.sqs_service.publish_international_payment",
                new_callable=AsyncMock,
            ) as mock_sqs,
        ):
            mock_crud_card.get = AsyncMock(return_value=debit_card)
            mock_crud_tx.create = AsyncMock(return_value=created_tx)

            result = await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert result.status == TransactionStatus.pending
        mock_sqs.assert_awaited_once_with(created_tx)

    @pytest.mark.asyncio
    async def test_national_debit_sufficient_balance_completes(
        self,
        customer_user: User,
        debit_card: Card,
        account: Account,
        mock_db: AsyncMock,
    ) -> None:
        """Debit national transaction with sufficient balance must complete."""
        payload = TransactionCreate(
            source_card=debit_card.id,
            destination_account="dest-account-uuid",
            amount=Decimal("100.00"),
            type=TransactionType.national,
        )
        created_tx = _make_transaction(TransactionStatus.completed)

        with (
            patch("app.services.transaction_service.crud_card") as mock_crud_card,
            patch("app.services.transaction_service.crud_account") as mock_crud_acc,
            patch("app.services.transaction_service.crud_transaction") as mock_crud_tx,
        ):
            mock_crud_card.get = AsyncMock(return_value=debit_card)
            mock_crud_acc.get_with_lock = AsyncMock(return_value=account)
            mock_crud_acc.deduct_balance = AsyncMock()
            mock_crud_tx.create = AsyncMock(return_value=created_tx)

            result = await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert result.status == TransactionStatus.completed
        mock_crud_acc.deduct_balance.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_national_debit_insufficient_balance_fails(
        self,
        customer_user: User,
        debit_card: Card,
        account: Account,
        mock_db: AsyncMock,
    ) -> None:
        """Debit national tx with insufficient balance must fail without deduction."""
        account.balance = Decimal("10.00")
        payload = TransactionCreate(
            source_card=debit_card.id,
            destination_account="dest-account-uuid",
            amount=Decimal("500.00"),
            type=TransactionType.national,
        )
        created_tx = _make_transaction(TransactionStatus.failed)

        with (
            patch("app.services.transaction_service.crud_card") as mock_crud_card,
            patch("app.services.transaction_service.crud_account") as mock_crud_acc,
            patch("app.services.transaction_service.crud_transaction") as mock_crud_tx,
        ):
            mock_crud_card.get = AsyncMock(return_value=debit_card)
            mock_crud_acc.get_with_lock = AsyncMock(return_value=account)
            mock_crud_acc.deduct_balance = AsyncMock()
            mock_crud_tx.create = AsyncMock(return_value=created_tx)

            result = await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert result.status == TransactionStatus.failed
        mock_crud_acc.deduct_balance.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_national_credit_completes_without_balance_check(
        self,
        customer_user: User,
        credit_card: Card,
        mock_db: AsyncMock,
    ) -> None:
        """Credit national transactions must complete without any balance check."""
        payload = TransactionCreate(
            source_card=credit_card.id,
            destination_account="dest-account-uuid",
            amount=Decimal("9999.00"),
            type=TransactionType.national,
        )
        created_tx = _make_transaction(
            TransactionStatus.completed, method=TransactionMethod.credit
        )

        with (
            patch("app.services.transaction_service.crud_card") as mock_crud_card,
            patch("app.services.transaction_service.crud_account") as mock_crud_acc,
            patch("app.services.transaction_service.crud_transaction") as mock_crud_tx,
        ):
            mock_crud_card.get = AsyncMock(return_value=credit_card)
            mock_crud_acc.get_with_lock = AsyncMock()
            mock_crud_tx.create = AsyncMock(return_value=created_tx)

            result = await transaction_service.create_transaction(
                payload=payload, db=mock_db, current_user=customer_user
            )

        assert result.status == TransactionStatus.completed
        mock_crud_acc.get_with_lock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_card_not_owned_raises_403(
        self,
        customer_user: User,
        debit_card: Card,
        mock_db: AsyncMock,
    ) -> None:
        """Using another user's card must raise HTTP 403."""
        from fastapi import HTTPException

        debit_card.account.user_id = uuid.uuid4()  # type: ignore[union-attr]  # different user
        payload = TransactionCreate(
            source_card=debit_card.id,
            destination_account="dest",
            amount=Decimal("10.00"),
            type=TransactionType.national,
        )

        with patch("app.services.transaction_service.crud_card") as mock_crud_card:
            mock_crud_card.get = AsyncMock(return_value=debit_card)
            with pytest.raises(HTTPException) as exc_info:
                await transaction_service.create_transaction(
                    payload=payload, db=mock_db, current_user=customer_user
                )

        assert exc_info.value.status_code == 403


class TestHandlePaymentWebhook:
    """Tests for transaction_service.handle_payment_webhook."""

    @pytest.mark.asyncio
    async def test_webhook_updates_pending_to_completed(
        self,
        mock_db: AsyncMock,
    ) -> None:
        """Webhook with status=completed must update a pending transaction."""
        tx = _make_transaction(
            TransactionStatus.pending, tx_type=TransactionType.international
        )
        payload = WebhookUpdate(status=TransactionStatus.completed)

        with patch("app.services.transaction_service.crud_transaction") as mock_crud_tx:
            mock_crud_tx.get = AsyncMock(return_value=tx)
            mock_crud_tx.update_status = AsyncMock(return_value=True)

            await transaction_service.handle_payment_webhook(
                transaction_id=tx.id, payload=payload, db=mock_db
            )

        mock_crud_tx.update_status.assert_awaited_once()
        call_kwargs = mock_crud_tx.update_status.call_args.kwargs
        assert call_kwargs["new_status"] == TransactionStatus.completed
        assert call_kwargs["expected_current_status"] == TransactionStatus.pending

    @pytest.mark.asyncio
    async def test_webhook_already_processed_raises_409(
        self,
        mock_db: AsyncMock,
    ) -> None:
        """Webhook on a non-pending transaction must raise HTTP 409."""
        from fastapi import HTTPException

        tx = _make_transaction(
            TransactionStatus.completed, tx_type=TransactionType.international
        )
        payload = WebhookUpdate(status=TransactionStatus.completed)

        with patch("app.services.transaction_service.crud_transaction") as mock_crud_tx:
            mock_crud_tx.get = AsyncMock(return_value=tx)
            mock_crud_tx.update_status = AsyncMock(return_value=False)

            with pytest.raises(HTTPException) as exc_info:
                await transaction_service.handle_payment_webhook(
                    transaction_id=tx.id, payload=payload, db=mock_db
                )

        assert exc_info.value.status_code == 409
