"""
Customer business logic service. Handles customer registration
(user + account creation) and session lifecycle (login / logout).
Follows the same session-based auth pattern as admin_service.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_session_token,
    hash_session_token,
    verify_password,
)
from app.crud.account import crud_account
from app.crud.audit_log import crud_audit_log, crud_user_session
from app.crud.user import crud_user
from app.models.account import Account
from app.models.audit_log import AuditLogAction, UserSession
from app.models.user import User, UserRole
from app.schemas.user import CustomerUserCreate

_SESSION_TTL_HOURS = 1


# Private helpers
def _extract_ip(request: Request) -> str | None:
    """Return the client IP from the request, or None if unavailable."""
    return request.client.host if request.client else None


# Registration
async def register(
    db: AsyncSession,
    request: Request,
    *,
    data: CustomerUserCreate,
) -> tuple[User, Account, UserSession, str]:
    """
    Register a new customer and create an associated bank account.
    Both the user and the account are created inside a single atomic DB
    transaction. If either insert fails, neither is committed.
    A session is opened immediately so the caller can return a session token
    without requiring a separate login step.

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

    ip = _extract_ip(request)
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


# Auth lifecycle
async def authenticate_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> User:
    """
    Validate email/password credentials and return the customer user.
    Uses a constant-time code path regardless of whether the email exists to
    prevent user-enumeration via timing attacks.

    Args:
    ----
        db: Active async database session.
        email: The email address submitted by the client.
        password: The plain-text password submitted by the client.

    Returns:
    -------
        The matching User instance with role=customer.

    Raises:
    ------
        HTTPException: 401 if the email is not found, the password is wrong,
            or the user does not have the customer role.

    """
    user = await crud_user.get_by_email(db, email=email)
    dummy_hash = "$2b$12$invalidhashpadding000000000000000000000000000000000000"
    stored_hash = user.password_hash if user is not None else dummy_hash
    password_ok = verify_password(password, stored_hash)

    if user is None or not password_ok or user.role != UserRole.customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )
    return user


async def login(
    db: AsyncSession,
    request: Request,
    *,
    email: str,
    password: str,
) -> tuple[UserSession, str]:
    """
    Authenticate a customer and create a server-side session.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        email: Customer email address.
        password: Plain-text password.

    Returns:
    -------
        A tuple of (UserSession ORM instance, raw_session_token string).

    Raises:
    ------
        HTTPException: 401 on bad credentials.
        HTTPException: 403 if the request IP does not match user.registered_ip.

    """
    user = await authenticate_user(db, email=email, password=password)
    ip = _extract_ip(request)

    if user.registered_ip and ip != user.registered_ip:
        async with db.begin():
            await crud_audit_log.create(
                db,
                user_id=user.id,
                action=AuditLogAction.login_failed,
                ip_address=ip,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Login rejected: request IP does not match the registered IP.",
        )

    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    expires_at = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(
        hours=_SESSION_TTL_HOURS
    )

    async with db.begin():
        await crud_audit_log.create(
            db, user_id=user.id, action=AuditLogAction.login, ip_address=ip
        )
        await crud_user_session.upsert(
            db,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip_address=ip,
        )

    session = await crud_user_session.get_by_user_id(db, user_id=user.id)
    assert session is not None  # noqa: S101 — we just upserted it
    return session, raw_token


async def logout(
    db: AsyncSession,
    request: Request,
    user: User,
) -> None:
    """
    Invalidate the customer session and record a logout audit event.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        user: Authenticated customer user.

    """
    ip = _extract_ip(request)
    async with db.begin():
        await crud_audit_log.create(
            db, user_id=user.id, action=AuditLogAction.logout, ip_address=ip
        )
        await crud_user_session.delete(db, user_id=user.id)
