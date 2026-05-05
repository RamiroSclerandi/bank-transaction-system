"""
Customer-facing transaction endpoints. These endpoints allow bank customers
to create, view, and list their own transactions. All routes in this module
require a valid Customer JWT. Ownership is enforced at the service layer —
customers can only access their own cards, accounts, and transactions.
"""

import uuid

from fastapi import APIRouter, Query, status

from app.deps import CustomerDep, DbDep
from app.schemas.transaction import TransactionCreate, TransactionRead
from app.services import transaction_service

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post(
    "",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new transaction",
)
async def create_transaction(
    payload: TransactionCreate,
    db: DbDep,
    current_user: CustomerDep,
) -> TransactionRead:
    """
    Create a new transaction for the current customer.

    Args:
    ----
        payload: The transaction creation payload.
        db: The database dependency.
        current_user: The current authenticated customer.

    Returns:
    -------
        TransactionRead: The created transaction.

    """
    transaction = await transaction_service.create_transaction(
        payload=payload,
        db=db,
        current_user=current_user,
    )
    return TransactionRead.model_validate(transaction)


@router.get(
    "/{transaction_id}",
    response_model=TransactionRead,
    summary="Get a transaction by ID (own transactions only)",
)
async def get_transaction(
    transaction_id: uuid.UUID,
    db: DbDep,
    current_user: CustomerDep,
) -> TransactionRead:
    """
    Get a transaction by ID for the current customer.

    Args:
    ----
        transaction_id: The UUID of the transaction to retrieve.
        db: The database dependency.
        current_user: The current authenticated customer.

    Returns:
    -------
        TransactionRead: The requested transaction.

    """
    transaction = await transaction_service.get_transaction_for_customer(
        db=db, transaction_id=transaction_id, current_user=current_user
    )
    return TransactionRead.model_validate(transaction)


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=list[TransactionRead],
    summary="List transactions for an account (own account only)",
)
async def list_account_transactions(
    account_id: uuid.UUID,
    db: DbDep,
    current_user: CustomerDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TransactionRead]:
    """
    List transactions for a specific account belonging to the current customer.

    Args:
    ----
        account_id: The UUID of the account to list transactions for.
        db: The database dependency.
        current_user: The current authenticated customer.
        limit: The maximum number of transactions to return.
        offset: The number of transactions to skip.

    Returns:
    -------
        list[TransactionRead]: A list of transactions for the specified account.

    """
    transactions = await transaction_service.list_account_transactions_for_customer(
        db=db,
        account_id=account_id,
        current_user=current_user,
        limit=limit,
        offset=offset,
    )
    return [TransactionRead.model_validate(t) for t in transactions]
