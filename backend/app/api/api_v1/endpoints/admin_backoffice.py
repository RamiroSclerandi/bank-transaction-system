"""
Bank Customer Support read-only transactions endpoints and user management.
All routes require:
  - A valid admin session token (AdminDep) — resolves session → user and
    validates expiry and IP consistency on every request.

Data reads do NOT produce audit log entries. Auth events are recorded exclusively
in the admin_auth endpoints (POST /admin/auth/login, POST /admin/auth/logout).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from app.crud.user import crud_user
from app.deps import AdminDep, DbDep
from app.models.transaction import TransactionStatus, TransactionType
from app.schemas.transaction import TransactionListFilters, TransactionRead
from app.schemas.user import AdminUserCreate, UserReadAdmin
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["admin-functions"])


@router.get(
    "/transactions",
    response_model=list[TransactionRead],
    summary="List all transactions with optional filters (admin only)",
)
async def list_transactions(
    db: DbDep,
    current_user: AdminDep,
    account_id: uuid.UUID | None = Query(default=None),
    tx_status: str | None = Query(default=None, alias="status"),
    tx_type: str | None = Query(default=None, alias="type"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[TransactionRead]:
    """
    List all transactions with optional filters (admin only).

    Args:
    ----
        db: Injected database session.
        current_user: Authenticated admin user.
        account_id: Filter by account ID. Defaults to None.
        tx_status: Filter by transaction status. Defaults to None.
        tx_type: Filter by transaction type. Defaults to None.
        date_from: Filter by start date. Defaults to None.
        date_to: Filter by end date. Defaults to None.
        limit: Maximum number of transactions to return. Defaults to 50.
        offset: Number of transactions to skip. Defaults to 0.

    Returns:
    -------
        list[TransactionRead]: List of transactions matching the filters.

    """
    filters = TransactionListFilters(
        account_id=account_id,
        status=TransactionStatus(tx_status) if tx_status else None,
        type=TransactionType(tx_type) if tx_type else None,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    transactions = await admin_service.list_transactions(db=db, filters=filters)
    return [TransactionRead.model_validate(t) for t in transactions]


@router.get(
    "/transactions/{transaction_id}",
    response_model=TransactionRead,
    summary="Get any transaction by ID (admin only)",
)
async def get_transaction_admin(
    transaction_id: uuid.UUID,
    db: DbDep,
    current_user: AdminDep,
) -> TransactionRead:
    """
    Get a transaction by its ID (admin only).

    Args:
    ----
        transaction_id: The ID of the transaction to retrieve.
        db: Injected database session.
        current_user: Authenticated admin user.

    Returns:
    -------
        TransactionRead: The transaction matching the given ID.

    """
    transaction = await admin_service.get_transaction(
        db=db, transaction_id=transaction_id
    )
    return TransactionRead.model_validate(transaction)


@router.post(
    "/users",
    response_model=UserReadAdmin,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new admin user (admin only)",
)
async def create_admin_user(
    body: AdminUserCreate,
    db: DbDep,
    current_user: AdminDep,
) -> UserReadAdmin:
    """
    Create a new backoffice admin user.

    Only an existing authenticated admin can create other admins.
    Returns 409 if the email is already registered.

    Args:
    ----
        body: New admin user data including plain-text password (will be hashed).
        db: Injected database session.
        current_user: The authenticated admin performing the action.

    Returns:
    -------
        The newly created admin user (PII included — admin-only route).

    Raises:
    ------
        HTTPException: 409 if the email is already in use.

    """
    existing = await crud_user.get_by_email(db, email=body.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    async with db.begin():
        user = await crud_user.create_admin(db, data=body)
    return UserReadAdmin.model_validate(user)
