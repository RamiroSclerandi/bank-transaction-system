"""
Shared FastAPI dependencies. All route handlers obtain their database sessions
and authenticated users through these dependencies, keeping the endpoint layer thin
and testable.
"""

import hmac
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_session_token
from app.crud.audit_log import crud_user_session
from app.crud.user import crud_user
from app.db.session import AsyncSessionLocal
from app.models.user import User, UserRole

_bearer = HTTPBearer(auto_error=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a request-scoped async database session.
    An AsyncSession bound to the current request lifecycle.
    """
    async with AsyncSessionLocal() as session:
        yield session


DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_admin(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    request: Request,
    db: DbDep,
) -> User:
    """
    Dependency: resolve and validate a session-based admin request.
    Extracts the Bearer token from the Authorization header, computes its
    SHA-256 digest, looks up the matching UserSession, and enforces:
      1. Session existence — 401 if not found (token invalid or logged out).
      2. Session expiry   — 401 if expires_at is in the past.
      3. IP consistency   — 403 if the request IP differs from the session IP.

    Args:
    ----
        credentials: Bearer credentials from the Authorization header.
        request: Incoming HTTP request (for IP extraction).
        db: Injected database session.

    Returns:
    -------
        The authenticated admin User loaded via the session relationship.

    Raises:
    ------
        HTTPException: 401 if the session is not found or has expired.
        HTTPException: 403 if the request IP does not match the session IP.

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_ip = request.client.host if request.client else None
    if session.ip_address and client_ip != session.ip_address:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request IP does not match the session IP.",
        )

    user = await crud_user.get(db, user_id=session.user_id)
    if user is None or user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin user not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_customer(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
    request: Request,
    db: DbDep,
) -> User:
    """
    Dependency: authenticated customer via session token.
    Resolves the Bearer token to a UserSession and validates:
      - Session existence (not logged out)
      - Session expiry (1-hour TTL)
      - IP consistency (request IP must match the IP used at login)

    Args:
    ----
        credentials: Bearer token from the Authorization header.
        request: Incoming HTTP request (IP extraction).
        db: Injected database session.

    Returns:
    -------
        The authenticated customer User.

    Raises:
    ------
        HTTPException: 401 if the session is missing, expired, or invalid.
        HTTPException: 403 if the request IP does not match the session IP.

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_ip = request.client.host if request.client else None
    if session.ip_address and client_ip != session.ip_address:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Request IP does not match the session IP.",
        )

    user = await crud_user.get(db, user_id=session.user_id)
    if user is None or user.role != UserRole.customer:
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
