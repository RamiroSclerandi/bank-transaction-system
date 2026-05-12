"""
Account management endpoints.

Authenticated routes (any role):
  - POST /accounts/add-balance  — add balance to own account

Admin routes:
  - POST /admin/accounts        — create a bank account for any user (AdminDep)
"""

from fastapi import APIRouter, HTTPException, status

from app.crud.account import crud_account
from app.crud.user import crud_user
from app.deps import AdminDep, CurrentUserDep, DbDep
from app.schemas.account import (  # type: ignore[attr-defined]
    AccountRead,
    AccountTopUp,
    AdminAccountCreate,
)

customer_accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])
admin_accounts_router = APIRouter(prefix="/admin/accounts", tags=["admin-accounts"])


@customer_accounts_router.post(
    "/add-balance",
    response_model=AccountRead,
    status_code=status.HTTP_200_OK,
    summary="Add balance to own account",
)
async def add_balance(
    body: AccountTopUp,
    db: DbDep,
    current_user: CurrentUserDep,
) -> AccountRead:
    """
    Credit the authenticated user's account with the given amount.
    Accessible by any authenticated user (admin or customer).

    Args:
    ----
        body: JSON payload with the amount to add.
        db: Injected database session.
        current_user: Authenticated user (any role).

    Returns:
    -------
        Updated AccountRead with the new balance.

    Raises:
    ------
        HTTPException: 404 if the user has no account.

    """
    async with db.begin():
        account = await crud_account.get_by_user(db, user_id=current_user.id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found.",
            )
        # Re-fetch with row lock for safe balance update
        locked_account = await crud_account.get_with_lock(db, account_id=account.id)
        if locked_account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account not found.",
            )
        await crud_account.add_balance(db, account=locked_account, amount=body.amount)  # type: ignore[attr-defined]

    await db.refresh(locked_account)
    return AccountRead.model_validate(locked_account)


@admin_accounts_router.post(
    "",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bank account for a customer user (admin only)",
)
async def admin_create_account(
    body: AdminAccountCreate,
    db: DbDep,
    current_user: AdminDep,
) -> AccountRead:
    """
    Create a bank account for an existing customer user.
    Admins do not have bank accounts; this is only valid for customer-role users.

    Args:
    ----
        body: JSON payload with the target user_id.
        db: Injected database session.
        current_user: Authenticated admin.

    Returns:
    -------
        The newly created AccountRead.

    Raises:
    ------
        HTTPException: 404 if the user does not exist.
        HTTPException: 422 if the user is not a customer.
        HTTPException: 409 if the user already has an account.

    """
    async with db.begin():
        user = await crud_user.get(db, user_id=body.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        existing = await crud_account.get_by_user(db, user_id=body.user_id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This user already has a bank account.",
            )
        account = await crud_account.create(db, user_id=body.user_id)

    return AccountRead.model_validate(account)
