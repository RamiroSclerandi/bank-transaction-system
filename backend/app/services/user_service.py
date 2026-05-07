"""
User management service.
Handles user creation for all roles:
  - create_admin: for internal use / scripts only.
  - register_customer: creates a customer user + associated bank account.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_session_token, hash_session_token
from app.crud.account import crud_account
from app.crud.audit_log import crud_user_session
from app.crud.user import crud_user
from app.models.audit_log import UserSession
from app.models.user import User
from app.schemas.user import AdminUserCreate, CustomerUserCreate

_SESSION_TTL_HOURS = 1


async def create_admin(
    db: AsyncSession,
    *,
    data: AdminUserCreate,
) -> User:
    """
    Create a new admin user.
    Only for internal use or scripts — not exposed via a public endpoint directly.
    The caller is responsible for ensuring the email does not already exist.

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
    existing = await crud_user.get_by_email(db, email=data.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )
    async with db.begin():
        user = await crud_user.create_admin(db, data=data)
    return user


async def register_customer(
    db: AsyncSession,
    request: Request,
    *,
    data: CustomerUserCreate,
) -> tuple[User, object, UserSession, str]:
    """
    Register a new customer and create an associated bank account.
    Both the user and the account are created inside a single atomic DB
    transaction. A session is opened immediately so the caller can return
    a session token without requiring a separate login step.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        data: Validated CustomerUserCreate payload.

    Returns:
    -------
        A tuple of (User, Account, UserSession, raw_token).

    Raises:
    ------
        HTTPException: 409 if the email is already registered.

    """
    existing = await crud_user.get_by_email(db, email=data.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    ip = request.client.host if request.client else None
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    expires_at = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(
        hours=_SESSION_TTL_HOURS
    )

    async with db.begin():
        user = await crud_user.create_customer(db, data=data)
        account = await crud_account.create(db, user_id=user.id)
        await crud_user_session.upsert(
            db,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip,
        )

    session = await crud_user_session.get_by_user_id(db, user_id=user.id)
    assert session is not None  # noqa: S101 — we just upserted it
    return user, account, session, raw_token
