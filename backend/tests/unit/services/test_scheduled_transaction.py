"""
Tests for transaction_service.process_scheduled_transaction.

This function is called exclusively by the internal endpoint triggered by the
Lambda worker (or the local polling worker). Idempotency is guaranteed via an
optimistic lock: the UPDATE changes status only if the current value is
'scheduled'. If two workers race, only one succeeds; the other receives 409.

AWS relevance:
  - In the national-debit path, no AWS service is involved.
  - In the international path, SQS is called. A publish failure should be
    treated the same as in create_transaction: the exception propagates and
    the DB transaction is rolled back, leaving the row in 'processing' state
    (the Lambda worker will not retry automatically — EventBridge will invoke
    a fresh execution on the next tick, but the row is stuck in 'processing').
    Operationally this requires a dead-letter queue or a manual status reset.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.services import transaction_service
from fastapi import HTTPException


def _make_scheduled_tx(
    tx_type: TransactionType = TransactionType.national,
    method: TransactionMethod = TransactionMethod.debit,
) -> MagicMock:
    """Build a minimal mock Transaction in SCHEDULED status."""
    tx = MagicMock(spec=Transaction)
    tx.id = uuid.uuid4()
    tx.status = TransactionStatus.scheduled
    tx.type = tx_type
    tx.method = method
    tx.origin_account = uuid.uuid4()
    tx.source_card = uuid.uuid4()
    tx.destination_account = "dest-account-123"
    tx.amount = Decimal("250.00")
    return tx


class TestProcessScheduledTransaction:
    """Tests for transaction_service.process_scheduled_transaction."""

    # ── 404 / 409 guard rails ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_transaction_not_found_raises_404(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """If the transaction does not exist the service must raise HTTP 404."""
        mock_crud_tx.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.process_scheduled_transaction(
                transaction_id=uuid.uuid4(), db=mock_db
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_already_claimed_raises_409(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """
        If update_status returns False (the optimistic lock condition failed),
        a 409 is raised. This happens when two workers race on the same row —
        the second one finds status='processing', not 'scheduled'.
        """
        tx = _make_scheduled_tx()
        mock_crud_tx.get = AsyncMock(return_value=tx)
        # False → the conditional UPDATE matched 0 rows
        mock_crud_tx.update_status = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as exc_info:
            await transaction_service.process_scheduled_transaction(
                transaction_id=tx.id, db=mock_db
            )

        assert exc_info.value.status_code == 409

    # ── National path ──────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_scheduled_national_debit_sufficient_balance_completes(
        self,
        mock_crud_tx: MagicMock,
        mock_crud_account: MagicMock,
        mock_db: AsyncMock,
    ):
        """
        A due national debit transaction with sufficient balance must be
        completed. The service claims the row (scheduled→processing) and then
        delegates to _process_national which executes deduct_balance and
        update_status(processing→completed).
        """
        tx = _make_scheduled_tx(TransactionType.national, TransactionMethod.debit)
        completed_tx = MagicMock(spec=Transaction)
        completed_tx.status = TransactionStatus.completed

        # mock_crud_account fixture pre-configures get_with_lock → account.balance=100
        # and deduct_balance = AsyncMock(). No overrides needed for the happy path.
        mock_crud_tx.get = AsyncMock(side_effect=[tx, completed_tx])
        mock_crud_tx.update_status = AsyncMock(return_value=True)

        await transaction_service.process_scheduled_transaction(
            transaction_id=tx.id, db=mock_db
        )

        # Claimed scheduled → processing
        first_update = mock_crud_tx.update_status.call_args_list[0]
        assert first_update.kwargs["new_status"] == TransactionStatus.processing
        assert (
            first_update.kwargs["expected_current_status"]
            == TransactionStatus.scheduled
        )
        # Balance was deducted because account.balance (1000) >= tx.amount (250)
        mock_crud_account.deduct_balance.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_scheduled_national_debit_insufficient_balance_fails(
        self,
        mock_crud_tx: MagicMock,
        mock_crud_account: MagicMock,
        mock_db: AsyncMock,
    ):
        """
        A due national debit transaction with insufficient balance must be
        marked FAILED without deducting any balance.
        """
        tx = _make_scheduled_tx(TransactionType.national, TransactionMethod.debit)
        failed_tx = MagicMock(spec=Transaction)
        failed_tx.status = TransactionStatus.failed

        # Override get_with_lock to return an account with very low balance
        low_balance_account = MagicMock()
        low_balance_account.balance = Decimal("1.00")  # less than tx.amount (250)
        mock_crud_account.get_with_lock = AsyncMock(return_value=low_balance_account)

        mock_crud_tx.get = AsyncMock(side_effect=[tx, failed_tx])
        mock_crud_tx.update_status = AsyncMock(return_value=True)

        await transaction_service.process_scheduled_transaction(
            transaction_id=tx.id, db=mock_db
        )

        mock_crud_account.deduct_balance.assert_not_awaited()
        # Final update_status call must set status to FAILED
        last_update = mock_crud_tx.update_status.call_args_list[-1]
        assert last_update.kwargs["new_status"] == TransactionStatus.failed

    @pytest.mark.asyncio
    async def test_scheduled_national_credit_completes_without_balance_check(
        self,
        mock_crud_tx: MagicMock,
        mock_crud_account: MagicMock,
        mock_db: AsyncMock,
    ):
        """
        A due national credit transaction must complete immediately.
        No balance check or deduction should happen (per FR-05).
        """
        tx = _make_scheduled_tx(TransactionType.national, TransactionMethod.credit)
        completed_tx = MagicMock(spec=Transaction)
        completed_tx.status = TransactionStatus.completed

        mock_crud_tx.get = AsyncMock(side_effect=[tx, completed_tx])
        mock_crud_tx.update_status = AsyncMock(return_value=True)

        await transaction_service.process_scheduled_transaction(
            transaction_id=tx.id, db=mock_db
        )

        mock_crud_account.get_with_lock.assert_not_awaited()
        mock_crud_account.deduct_balance.assert_not_awaited()

    # ── International path (AWS SQS) ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_scheduled_international_publishes_to_sqs_and_moves_to_pending(
        self,
        mock_crud_tx: MagicMock,
        mock_sqs: AsyncMock,
        mock_db: AsyncMock,
    ):
        """
        A due international transaction must be moved from PROCESSING to PENDING
        and its details published to SQS so the external payment handler can pick
        it up.

        AWS relevance: if the SQS queue URL is wrong or credentials are missing,
        publish_international_payment raises a botocore ClientError here.
        """
        tx = _make_scheduled_tx(TransactionType.international, TransactionMethod.debit)

        mock_crud_tx.get = AsyncMock(return_value=tx)
        # First call: scheduled→processing (claimed); second call: processing→pending
        mock_crud_tx.update_status = AsyncMock(return_value=True)

        await transaction_service.process_scheduled_transaction(
            transaction_id=tx.id, db=mock_db
        )

        mock_sqs.assert_awaited_once_with(tx)
        # Verify the second update_status call sets PENDING
        pending_call = mock_crud_tx.update_status.call_args_list[1]
        assert pending_call.kwargs["new_status"] == TransactionStatus.pending
        assert (
            pending_call.kwargs["expected_current_status"]
            == TransactionStatus.processing
        )

    @pytest.mark.asyncio
    async def test_sqs_publish_failure_propagates_and_leaves_row_in_processing(
        self,
        mock_crud_tx: MagicMock,
        mock_sqs: AsyncMock,
        mock_db: AsyncMock,
    ):
        """
        If SQS publish raises (e.g. NoCredentialsError, ClientError, network
        timeout), the exception propagates out of process_scheduled_transaction.
        The DB context manager does NOT suppress it (return_value=False on __aexit__),
        triggering a rollback on the open transaction.

        Operationally: the row remains in 'scheduled' status after the rollback.
        The next Lambda/worker invocation will re-claim it.

        AWS relevance: this is the failure mode when SQS_INTERNATIONAL_QUEUE_URL
        is misconfigured or IAM permissions are missing.
        """
        tx = _make_scheduled_tx(TransactionType.international, TransactionMethod.debit)
        mock_crud_tx.get = AsyncMock(return_value=tx)
        mock_crud_tx.update_status = AsyncMock(return_value=True)
        mock_sqs.side_effect = RuntimeError("SQS NoCredentialsError")

        with pytest.raises(RuntimeError, match="SQS NoCredentialsError"):
            await transaction_service.process_scheduled_transaction(
                transaction_id=tx.id, db=mock_db
            )
