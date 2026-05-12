"""
User management service.
Handles user creation for all roles:
  - create_admin: for internal use / scripts only.
  - register_customer: creates a customer user + associated bank account.
"""

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.account import crud_account
from app.crud.user import crud_user
from app.models.account import Account
from app.models.user import User
from app.schemas.user import AdminUserCreate, CustomerUserCreate


def _raise_for_integrity_error(exc: IntegrityError) -> None:
    constraint: str = getattr(exc.orig, "constraint_name", "") or ""
    if "email" in constraint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    if "national_id" in constraint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this national_id already exists.",
        )
    if "phone" in constraint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this phone already exists.",
        )


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
        HTTPException: 409 if the email, national_id, or phone is already registered.

    """
    try:
        async with db.begin():
            existing = await crud_user.get_by_email(db, email=data.email)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this email already exists.",
                )
            existing_nid = await crud_user.get_by_national_id(
                db, national_id=data.national_id
            )
            if existing_nid is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this national_id already exists.",
                )
            existing_phone = await crud_user.get_by_phone(db, phone=data.phone)
            if existing_phone is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this phone already exists.",
                )
            user = await crud_user.create_admin(db, data=data)
        return user
    except IntegrityError as exc:
        _raise_for_integrity_error(exc)
        raise


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
        HTTPException: 409 if the email, national_id, or phone is already registered.

    """
    try:
        async with db.begin():
            existing = await crud_user.get_by_email(db, email=data.email)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this email already exists.",
                )
            existing_nid = await crud_user.get_by_national_id(
                db, national_id=data.national_id
            )
            if existing_nid is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this national_id already exists.",
                )
            existing_phone = await crud_user.get_by_phone(db, phone=data.phone)
            if existing_phone is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A user with this phone already exists.",
                )
            user = await crud_user.create_customer(db, data=data)
            account = await crud_account.create(db, user_id=user.id)
        return user, account
    except IntegrityError as exc:
        _raise_for_integrity_error(exc)
        raise
