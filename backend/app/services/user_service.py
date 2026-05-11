"""
User management service.
Handles user creation for all roles:
  - create_admin: for internal use / scripts only.
  - register_customer: creates a customer user + associated bank account.
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.account import crud_account
from app.crud.user import crud_user
from app.models.account import Account
from app.models.user import User
from app.schemas.user import AdminUserCreate, CustomerUserCreate


async def create_admin(
    db: AsyncSession,
    *,
    data: AdminUserCreate,
) -> User:
    """
    Create a new admin user.
    Only for internal use or scripts — not exposed via a public endpoint directly.

    Args:
    ----
        db: Active async database session.
        data: Validated AdminUserCreate payload.

    Returns:
    -------
        The newly created admin User instance.

    Raises:
    ------
        HTTPException: 409 if the email is already registered.

    """
    async with db.begin():
        existing = await crud_user.get_by_email(db, email=data.email)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )
        user = await crud_user.create_admin(db, data=data)
    return user


async def register_customer(
    db: AsyncSession,
    *,
    data: CustomerUserCreate,
) -> tuple[User, Account]:
    """
    Register a new customer and create an associated bank account.
    Both the user and the account are created inside a single atomic DB
    transaction. A session is NOT created here — the client must call
    POST /auth/login after registration to obtain a session token.

    Args:
    ----
        db: Active async database session.
        data: Validated CustomerUserCreate payload.

    Returns:
    -------
        A tuple of (User, Account).

    Raises:
    ------
        HTTPException: 409 if the email is already registered.

    """
    async with db.begin():
        existing = await crud_user.get_by_email(db, email=data.email)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )
        user = await crud_user.create_customer(db, data=data)
        account = await crud_account.create(db, user_id=user.id)

    return user, account
