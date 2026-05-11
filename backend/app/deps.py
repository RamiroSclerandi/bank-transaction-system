"""
Shared FastAPI dependencies. All route handlers obtain their database sessions
and authenticated users through these dependencies, keeping the endpoint layer thin
and testable.

Dependency hierarchy:
    get_current_user  →  validates token + session + expiry, returns User
    get_current_admin →  calls get_current_user, checks role=admin + IP
    get_current_customer → calls get_current_user, checks role=customer
"""

import hmac
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_session_token
from app.crud.audit_log import crud_session_history, crud_user_session
from app.crud.user import crud_user
from app.db.session import AsyncSessionLocal
from app.models.audit_log import SessionEvent
from app.models.user import User, UserRole

_bearer = HTTPBearer(auto_error=True)


async def _cleanup_expired_session(user_id: uuid.UUID) -> None:
    """
    Fire-and-forget background task: delete an expired session row and
    record a SessionHistory entry with event=expired.
    Opens its own DB session so it can run after the request session is closed.
    """
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                session = await crud_user_session.get_by_user_id(db, user_id=user_id)
                token_hash = session.token_hash if session is not None else ""
                await crud_user_session.delete(db, user_id=user_id)
                await crud_session_history.create(
                    db,
                    user_id=user_id,
                    event=SessionEvent.expired,
                    token_hash=token_hash,
                    ip_address=None,
                )
    except Exception:
        logger.exception(
            "Background cleanup failed for expired session (user_id={user_id})",
            user_id=user_id,
        )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a request-scoped async database session.
    An AsyncSession bound to the current request lifecycle.
    """
    async with AsyncSessionLocal() as session:
        yield session


DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    db: DbDep,
    background_tasks: BackgroundTasks,
) -> User:
    """
    Dependency: resolve and validate a session-based request.
    Extracts the Bearer token, hashes it, looks up the matching UserSession,
    and enforces session existence and expiry. Role-agnostic.

    Args:
    ----
        credentials: Bearer credentials from the Authorization header.
        db: Injected database session.
        background_tasks: FastAPI BackgroundTasks for post-response cleanup.

    Returns:
    -------
        The authenticated User loaded via the session relationship.

    Raises:
    ------
        HTTPException: 401 if the session is not found or has expired.

    """
    token_hash = hash_session_token(credentials.credentials)
    session = await crud_user_session.get_by_token_hash(db, token_hash=token_hash)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = datetime.now(tz=UTC).replace(tzinfo=None)
    if session.expires_at < now:
        background_tasks.add_task(_cleanup_expired_session, session.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await crud_user.get(db, user_id=session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # End the implicit read-only transaction opened by autobegin so the service
    await db.commit()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_admin(
    user: CurrentUserDep,
    request: Request,
) -> User:
    """
    Dependency: enforce admin role and IP restriction.
    Calls get_current_user first, then validates:
      1. Role — 401 if not admin.
      2. IP consistency — 403 if registered_ip is set and does not match.

    Args:
    ----
        user: Authenticated user resolved by get_current_user.
        request: Incoming HTTP request (for IP extraction).

    Returns:
    -------
        The authenticated admin User.

    Raises:
    ------
        HTTPException: 401 if the user does not have the admin role.
        HTTPException: 403 if registered_ip is set and does not match the request IP.

    """
    if user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin privileges required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_ip = request.client.host if request.client else None
    if user.registered_ip and client_ip != user.registered_ip:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request IP does not match the registered IP.",
        )

    return user


async def get_current_customer(
    user: CurrentUserDep,
) -> User:
    """
    Dependency: enforce customer role.
    Calls get_current_user first, then validates role=customer.

    Args:
    ----
        user: Authenticated user resolved by get_current_user.

    Returns:
    -------
        The authenticated customer User.

    Raises:
    ------
        HTTPException: 401 if the user does not have the customer role.

    """
    if user.role != UserRole.customer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer user not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def verify_internal_api_key(
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """
    Dependency: validate the internal service API key.
    Used on endpoints called by the Lambda worker or other internal services.
    Constant-time comparison prevents timing attacks.

    Args:
    ----
        x_internal_api_key: Value of the X-Internal-Api-Key request header.

    Raises:
    ------
        HTTPException: 403 if the key is absent or does not match.

    """
    expected = settings.INTERNAL_SERVICE_API_KEY.encode()
    provided = (x_internal_api_key or "").encode()

    if not hmac.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden.",
        )


CustomerDep = Annotated[User, Depends(get_current_customer)]
AdminDep = Annotated[User, Depends(get_current_admin)]
InternalAuthDep = Annotated[None, Depends(verify_internal_api_key)]
