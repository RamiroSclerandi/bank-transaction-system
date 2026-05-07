"""
Authentication business logic service.
Centralises login, logout and session management for all user roles.
This service is role-agnostic: it validates credentials and manages
sessions without knowledge of what a user can do once authenticated.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_session_token,
    hash_session_token,
    verify_password,
)
from app.crud.audit_log import crud_audit_log, crud_user_session
from app.crud.user import crud_user
from app.models.audit_log import AuditLogAction, UserSession
from app.models.user import User, UserRole

_SESSION_TTL_HOURS = 1


# Private Helper
def _extract_ip(request: Request) -> str | None:
    """Return the client IP from the request, or None if unavailable."""
    return request.client.host if request.client else None


async def authenticate_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    role: UserRole,
) -> User:
    """
    Validate email/password credentials and return the user if the role matches.
    Uses a constant-time code path regardless of whether the email exists to
    prevent user-enumeration via timing attacks.

    Args:
    ----
        db: Active async database session.
        email: The email address submitted by the client.
        password: The plain-text password submitted by the client.
        role: The expected role of the user (admin or customer).

    Returns:
    -------
        The matching User instance.

    Raises:
    ------
        HTTPException: 401 if the email is not found, the password is wrong,
            or the user does not have the expected role.

    """
    user = await crud_user.get_by_email(db, email=email)
    # Always call verify_password even on miss to avoid leaking whether the
    # email exists via timing differences.
    dummy_hash = "$2b$12$invalidhashpadding000000000000000000000000000000000000"
    stored_hash = user.password_hash if user is not None else dummy_hash
    password_ok = verify_password(password, stored_hash)

    if user is None or not password_ok or user.role != role:
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
    role: UserRole,
) -> tuple[UserSession, str]:
    """
    Authenticate a user and create a server-side session.
    Validates credentials, enforces IP policy if ``user.registered_ip`` is set,
    creates or replaces the UserSession row, and records a login audit event.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        email: User email address.
        password: Plain-text password.
        role: Expected user role (admin or customer).

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
    user = await authenticate_user(db, email=email, password=password, role=role)
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
    Invalidate the user session and record a logout audit event.

    Args:
    ----
        db: Active async database session.
        request: Incoming HTTP request (IP extraction).
        user: Authenticated user.

    """
    ip = _extract_ip(request)
    async with db.begin():
        await crud_audit_log.create(
            db, user_id=user.id, action=AuditLogAction.logout, ip_address=ip
        )
        await crud_user_session.delete(db, user_id=user.id)
