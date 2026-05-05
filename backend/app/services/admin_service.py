"""
Admin (BCS) business logic service. Auth events (login / logout) are recorded
in the audit log. Handles transaction data access and admin session lifecycle.
Data reads do NOT produce audit log entries — reads are not state-change events.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_session_token,
    hash_session_token,
    verify_password,
)
from app.crud.audit_log import crud_audit_log, crud_user_session
from app.crud.transaction import crud_transaction
from app.crud.user import crud_user
from app.models.audit_log import AuditLogAction, UserSession
from app.models.transaction import Transaction
from app.models.user import User, UserRole
from app.schemas.transaction import TransactionListFilters

_SESSION_TTL_HOURS = 1


# Private helpers
def _extract_ip(request: Request) -> str | None:
    """Return the client IP from the request, or None if unavailable."""
    return request.client.host if request.client else None


# Auth lifecycle
async def authenticate_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
) -> User:
    """
    Validate email/password credentials and return the admin user.

    Args:
    ----
        db: Active async database session.
        email: The email address submitted by the client.
        password: The plain-text password submitted by the client.

    Returns:
    -------
        The matching User instance with role=admin.

    Raises:
    ------
        HTTPException: 401 if the email is not found, the password is wrong,
            or the user does not have the admin role.

    """
    user = await crud_user.get_by_email(db, email=email)
    # always call verify_password even on miss to avoid leaking
    # whether the email exists via timing differences.
    dummy_hash = "$2b$12$invalidhashpadding000000000000000000000000000000000000"
    stored_hash = user.password_hash if user is not None else dummy_hash
    password_ok = verify_password(password, stored_hash)

    if user is None or not password_ok or user.role != UserRole.admin:
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
    Authenticate an admin user and create a server-side session.
    Validates credentials, enforces IP policy, creates or replaces the
    UserSession row, and records a login audit event.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        email: Admin email address.
        password: Plain-text password.

    Returns:
    -------
        A tuple of (UserSession ORM instance, raw_session_token string).
        The raw token must be returned to the client; only its SHA-256 digest
        is stored in the database.

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
    Invalidate the admin session and record a logout audit event.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        user: Authenticated admin user.

    """
    ip = _extract_ip(request)
    async with db.begin():
        await crud_audit_log.create(
            db, user_id=user.id, action=AuditLogAction.logout, ip_address=ip
        )
        await crud_user_session.delete(db, user_id=user.id)


# Session validation
async def require_active_session(
    db: AsyncSession,
    user: User,
) -> None:
    """
    Verify that an active, non-expired session exists for the admin user.
    Called as a guard on every admin data endpoint. Rejects requests when the
    session has been invalidated (e.g. after logout from another device).

    Args:
    ----
        db: Active async database session.
        user: Authenticated admin user.

    Raises:
    ------
        HTTPException: 401 if no active session exists or it has expired.

    """
    session = await crud_user_session.get_by_user_id(db, user_id=user.id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active session. Please log in again.",
        )
    now = datetime.now(tz=UTC).replace(tzinfo=None)
    if session.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )


# Data access
async def list_transactions(
    db: AsyncSession,
    filters: TransactionListFilters,
) -> list[Transaction]:
    """
    Return filtered transactions.

    Args:
    ----
        db: Active async database session.
        filters: Query filters to apply.

    Returns:
    -------
        A list of Transaction ORM instances matching the filters.

    """
    return await crud_transaction.list_filtered(db, filters=filters)


async def get_transaction(
    db: AsyncSession,
    transaction_id: uuid.UUID,
) -> Transaction:
    """
    Return a single transaction by ID.

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
