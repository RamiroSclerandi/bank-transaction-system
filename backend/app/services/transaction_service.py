"""
Transaction business logic service, contains the processing decision tree
and all business rules for transaction creation and scheduled-transaction execution.
Decision tree:
    Incoming transaction
    ├─ scheduled_for in the future? → persist as SCHEDULED (stop)
    ├─ type = international?        → persist as PENDING, publish to SQS (stop)
    └─ type = national
          ├─ method = debit → serializable DB transaction:
          │     ├─ balance >= amount → deduct balance + persist as COMPLETED
          │     └─ balance < amount  → persist as FAILED (no deduction)
          └─ method = credit → persist as COMPLETED (no balance check)
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.account import crud_account
from app.crud.card import crud_card
from app.crud.transaction import crud_transaction
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListFilters,
    WebhookUpdate,
)
from app.services import sqs_service


async def create_transaction(
    payload: TransactionCreate,
    db: AsyncSession,
    current_user: User,
) -> Transaction:
    """
    Create and route a new transaction following the processing decision tree.

    Args:
    ----
        payload: Validated transaction creation schema.
        db: Active async database session.
        current_user: Authenticated user extracted from the JWT.

    Returns:
    -------
        The persisted transaction as an ORM instance.

    Raises:
    ------
        HTTPException: 403 if the source card does not belong to current_user.
        HTTPException: 404 if the source card is not found.
        HTTPException: 409 if a reversal target transaction is not found.

    """
    # 1. Verify card exists and belongs to the current user
    card = await crud_card.get(db, card_id=payload.source_card)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Card not found."
        )
    if card.account.user_id != current_user.id:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Card does not belong to the authenticated user.",
        )

    origin_account_id = card.account_id
    method = TransactionMethod(card.card_type.value)
    now = datetime.now(tz=UTC).replace(tzinfo=None)

    # 2. Apply the processing decision tree
    async with db.begin():
        # Branch A: Scheduled transaction
        if payload.scheduled_for and payload.scheduled_for > now:
            return await crud_transaction.create(
                db,
                source_card=payload.source_card,
                origin_account=origin_account_id,
                destination_account=payload.destination_account,
                amount=payload.amount,
                transaction_type=payload.type,
                method=method,
                status=TransactionStatus.scheduled,
                scheduled_for=payload.scheduled_for,
                reversal_of=payload.reversal_of,
            )

        # Branch B: International payment → async via SQS
        if payload.type == TransactionType.international:
            transaction = await crud_transaction.create(
                db,
                source_card=payload.source_card,
                origin_account=origin_account_id,
                destination_account=payload.destination_account,
                amount=payload.amount,
                transaction_type=payload.type,
                method=method,
                status=TransactionStatus.pending,
                reversal_of=payload.reversal_of,
            )
            # Publish to SQS — if this fails the DB transaction is rolled back
            await sqs_service.publish_international_payment(transaction)
            return transaction

        # Branch C: National payment
        return await _process_national(
            db=db,
            source_card=payload.source_card,
            origin_account_id=origin_account_id,
            destination_account=payload.destination_account,
            amount=payload.amount,
            method=method,
            reversal_of=payload.reversal_of,
        )


async def process_scheduled_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession,
) -> Transaction:
    """
    Execute a scheduled transaction that is now due. Called exclusively by the
    Lambda worker via the internal endpoint. Uses an optimistic lock to guarantee
    idempotent, at-most-once processing.

    Args:
    ----
        transaction_id: UUID of the scheduled transaction to process.
        db: Active async database session.

    Returns:
    -------
        The updated Transaction instance.

    Raises:
    ------
        HTTPException: 404 if the transaction is not found.
        HTTPException: 409 if the transaction is already being processed

    """
    transaction = await crud_transaction.get(db, transaction_id=transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found."
        )

    # Optimistic lock: claim the row from 'scheduled' → 'processing'
    async with db.begin():
        claimed = await crud_transaction.update_status(
            db,
            transaction_id=transaction_id,
            new_status=TransactionStatus.processing,
            expected_current_status=TransactionStatus.scheduled,
        )
        if not claimed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Transaction is already being processed.",
            )

        # Re-apply national/international routing (no scheduled check this time)
        if transaction.type == TransactionType.international:
            await crud_transaction.update_status(
                db,
                transaction_id=transaction_id,
                new_status=TransactionStatus.pending,
                expected_current_status=TransactionStatus.processing,
            )
            await sqs_service.publish_international_payment(transaction)
        else:
            method = TransactionMethod(transaction.method.value)
            await _process_national(
                db=db,
                source_card=transaction.source_card,
                origin_account_id=transaction.origin_account,
                destination_account=transaction.destination_account,
                amount=transaction.amount,
                method=method,
                existing_transaction_id=transaction_id,
            )

    await db.refresh(transaction)
    return transaction


async def handle_payment_webhook(
    transaction_id: uuid.UUID,
    payload: WebhookUpdate,
    db: AsyncSession,
) -> Transaction:
    """
    Update a pending international transaction from the external processor.
    Called via the internal webhook endpoint. Only transitions allowed are
    pending → completed or pending → failed.

    Args:
    ----
        transaction_id: UUID of the transaction to update.
        payload: Webhook payload containing the final status.
        db: Active async database session.

    Returns:
    -------
        The updated Transaction instance.

    Raises:
    ------
        HTTPException: 404 if the transaction is not found.
        HTTPException: 409 if the transaction is not in 'pending' status.

    """
    transaction = await crud_transaction.get(db, transaction_id=transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found."
        )

    async with db.begin():
        updated = await crud_transaction.update_status(
            db,
            transaction_id=transaction_id,
            new_status=payload.status,
            expected_current_status=TransactionStatus.pending,
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Transaction is not in 'pending' status "
                    f"(current: {transaction.status.value})."
                ),
            )

    logger.info(
        "Webhook updated transaction {tx_id} to {new_status}",
        tx_id=transaction_id,
        new_status=payload.status.value,
    )
    await db.refresh(transaction)
    return transaction


async def _process_national(
    db: AsyncSession,
    source_card: uuid.UUID,
    origin_account_id: uuid.UUID,
    destination_account: str,
    amount: Decimal,
    method: TransactionMethod,
    reversal_of: uuid.UUID | None = None,
    existing_transaction_id: uuid.UUID | None = None,
) -> Transaction:
    """
    Apply national payment rules inside the caller's open transaction.
    For debit cards: acquires a row lock on the account, checks balance,
    deducts atomically, and persists COMPLETED or FAILED.
    For credit cards: persists COMPLETED immediately (no balance check).

    Args:
    ----
        db: Async session with an active BEGIN (caller's responsibility).
        source_card: Card UUID used for the transaction.
        origin_account_id: The account to debit.
        destination_account: Target account identifier.
        amount: Transaction amount.
        method: debit or credit.
        reversal_of: Optional reference to original transaction.
        existing_transaction_id: If set, update an existing row instead of
            creating a new one (used for scheduled transaction execution).

    Returns:
    -------
        The persisted or updated Transaction.

    """
    if method == TransactionMethod.debit:
        account = await crud_account.get_with_lock(db, account_id=origin_account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Origin account not found.",
            )
        if account.balance >= amount:
            await crud_account.deduct_balance(db, account=account, amount=amount)
            final_status = TransactionStatus.completed
        else:
            final_status = TransactionStatus.failed
    else:
        # Credit card: skip balance check per FR-05
        final_status = TransactionStatus.completed

    if existing_transaction_id:
        await crud_transaction.update_status(
            db,
            transaction_id=existing_transaction_id,
            new_status=final_status,
            expected_current_status=TransactionStatus.processing,
        )
        tx = await crud_transaction.get(db, transaction_id=existing_transaction_id)
        assert tx is not None  # noqa: S101
        return tx

    return await crud_transaction.create(
        db,
        source_card=source_card,
        origin_account=origin_account_id,
        destination_account=destination_account,
        amount=amount,
        transaction_type=TransactionType.national,
        method=method,
        status=final_status,
        reversal_of=reversal_of,
    )


async def get_transaction_for_customer(
    db: AsyncSession,
    transaction_id: uuid.UUID,
    current_user: User,
) -> Transaction:
    """
    Retrieve a transaction, enforcing ownership by the authenticated customer.

    Args:
    ----
        db: Active async database session.
        transaction_id: UUID of the transaction to retrieve.
        current_user: Authenticated customer.

    Returns:
    -------
        The Transaction ORM instance.

    Raises:
    ------
        HTTPException: 404 if the transaction is not found.
        HTTPException: 403 if the transaction does not belong to the user.

    """
    transaction = await crud_transaction.get(db, transaction_id=transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found."
        )
    if transaction.account.user_id != current_user.id:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )
    return transaction


async def list_account_transactions_for_customer(
    db: AsyncSession,
    account_id: uuid.UUID,
    current_user: User,
    limit: int,
    offset: int,
) -> list[Transaction]:
    """
    List transactions for an account, enforcing ownership by the authenticated customer.

    Args:
    ----
        db: Active async database session.
        account_id: UUID of the account to list transactions for.
        current_user: Authenticated customer.
        limit: Max number of records to return.
        offset: Pagination offset.

    Returns:
    -------
        A list of Transaction ORM instances ordered by date descending.

    Raises:
    ------
        HTTPException: 403 if the account does not belong to the current user.

    """
    account = await crud_account.get(db, account_id=account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
        )
    return await crud_transaction.list_by_account(
        db, account_id=account_id, limit=limit, offset=offset
    )


async def list_transactions_admin(
    db: AsyncSession,
    filters: TransactionListFilters,
) -> list[Transaction]:
    """
    Return filtered transactions for admin use.

    Args:
    ----
        db: Active async database session.
        filters: Query filters to apply.

    Returns:
    -------
        A list of Transaction ORM instances matching the filters.

    """
    return await crud_transaction.list_filtered(db, filters=filters)


async def get_transaction_admin(
    db: AsyncSession,
    transaction_id: uuid.UUID,
) -> Transaction:
    """
    Return a single transaction by ID for admin use.

    Args:
    ----
        db: Active async database session.
        transaction_id: UUID of the transaction to retrieve.

    Returns:
    -------
        The Transaction ORM instance.

    Raises:
    ------
        HTTPException: 404 if the transaction does not exist.

    """
    transaction = await crud_transaction.get(db, transaction_id=transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found."
        )
    return transaction
