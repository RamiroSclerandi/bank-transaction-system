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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hmac_pan
from app.crud.account import crud_account
from app.crud.card import crud_card
from app.crud.transaction import crud_transaction
from app.models.card import Card
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.schemas.card import CardInput
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListFilters,
)
from app.services import sqs_service


async def _resolve_card(
    db: AsyncSession,
    *,
    card_input: CardInput,
    current_user: User,
) -> Card:
    """
    Resolve a card for the current user using get-or-create semantics.

    1. Compute HMAC-SHA256 of the PAN and look up the card by digest.
    2. If found, verify it belongs to the current user's account.
    3. If not found, create it under the user's account.

    A concurrent INSERT race on the unique `number_hmac` column is handled by
    catching IntegrityError, rolling back, and re-fetching.

    Args:
    ----
        db: Active async database session.
        card_input: Validated card details from the transaction payload.
        current_user: Authenticated customer.

    Returns:
    -------
        The resolved or newly created Card instance.

    Raises:
    ------
        HTTPException: 403 if the card exists but belongs to a different user.
        HTTPException: 404 if the user's account is not found.

    """
    pan_hmac = hmac_pan(card_input.number, settings.PAN_HMAC_KEY)
    last4 = card_input.number.replace("-", "")[-4:]

    try:
        async with db.begin():
            card = await crud_card.get_by_hmac(db, number_hmac=pan_hmac)
            if card is not None:
                if card.account.user_id != current_user.id:  # type: ignore[union-attr]
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Card does not belong to the authenticated user.",
                    )
                return card

            account = await crud_account.get_by_user(db, user_id=current_user.id)
            if account is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User account not found.",
                )

            card = await crud_card.create(
                db,
                account_id=account.id,
                card_type=card_input.card_type,
                number_hmac=pan_hmac,
                number_last4=last4,
                expiration_month=card_input.expiration_month,
                expiration_year=card_input.expiration_year,
            )
    except IntegrityError:
        # Concurrent request created the same card — re-fetch it
        async with db.begin():
            card = await crud_card.get_by_hmac(db, number_hmac=pan_hmac)
        if card is None or card.account.user_id != current_user.id:  # type: ignore[union-attr]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Card does not belong to the authenticated user.",
            )

    return card  # type: ignore[return-value]


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
        HTTPException: 402 if the debit transaction is rejected due to insufficient
        funds. The FAILED transaction is already committed to the DB as an audit record.
        HTTPException: 403 if the source card does not belong to current_user.
        HTTPException: 404 if the user's account is not found, or if a
        reversal target transaction is not found.

    """
    # 1. Resolve card (get-or-create by number) and verify ownership
    card = await _resolve_card(db, card_input=payload.card, current_user=current_user)

    origin_account_id = card.account_id
    method = TransactionMethod(card.card_type.value)
    now = datetime.now(tz=UTC).replace(tzinfo=None)

    # 2. Validate reversal target and apply the processing decision tree — single
    # transaction so no autobegin is active before the explicit db.begin() call.
    national_transaction: Transaction
    async with db.begin():
        if payload.reversal_of is not None:
            original = await crud_transaction.get(
                db, transaction_id=payload.reversal_of
            )
            if original is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Original transaction '{payload.reversal_of}' not found.",
                )
        if payload.scheduled_for and payload.scheduled_for > now:
            return await crud_transaction.create(
                db,
                source_card=card.id,
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
                source_card=card.id,
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

        # Branch C: National payment — captured outside the with-block so we can
        # raise 402 after the FAILED record is already committed (audit trail).
        national_transaction = await _process_national(
            db=db,
            source_card=card.id,
            origin_account_id=origin_account_id,
            destination_account=payload.destination_account,
            amount=payload.amount,
            method=method,
            reversal_of=payload.reversal_of,
        )

    # Post-commit: raise 402 if the debit was rejected due to insufficient funds.
    # The FAILED transaction record is already persisted for audit purposes.
    if (
        method == TransactionMethod.debit
        and national_transaction.status == TransactionStatus.failed
    ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient funds.",
        )

    return national_transaction


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
    # Optimistic lock: claim the row from 'scheduled' → 'processing'
    # The initial get() is inside the same db.begin() to avoid triggering autobegin
    # before the explicit transaction start.
    async with db.begin():
        transaction = await crud_transaction.get(db, transaction_id=transaction_id)
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found."
            )

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
