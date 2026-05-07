"""
Unified authentication endpoints for all user roles.
  - POST /auth/login        — customer login
  - POST /auth/logout       — customer logout
  - POST /admin/auth/login  — admin login
  - POST /admin/auth/logout — admin logout
"""

from fastapi import APIRouter, Request, status

from app.deps import AdminDep, CustomerDep, DbDep
from app.models.user import UserRole
from app.schemas.audit_log import LoginRequest, LoginResponse
from app.services import auth_service

customer_auth_router = APIRouter(prefix="/auth", tags=["customer-auth"])
admin_auth_router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


# ── Customer ───
@customer_auth_router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate a customer and create a server-side session",
)
async def customer_login(
    body: LoginRequest,
    request: Request,
    db: DbDep,
) -> LoginResponse:
    """
    Validates customer credentials (bcrypt), enforces IP policy if
    registered_ip is set, creates or replaces the active UserSession, and
    returns a session token.

    Args:
    ----
        body: JSON body containing email and password.
        request: Incoming HTTP request (used to extract the client IP).
        db: Injected database session.

    Returns:
    -------
        A LoginResponse with the opaque session_token and its expiry time.

    Raises:
    ------
        HTTPException: 401 if credentials are invalid.
        HTTPException: 403 if the request IP does not match registered_ip.

    """
    session, raw_token = await auth_service.login(
        db=db,
        request=request,
        email=body.email,
        password=body.password,
        role=UserRole.customer,
    )
    return LoginResponse(session_token=raw_token, expires_at=session.expires_at)


@customer_auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate the current customer session",
)
async def customer_logout(
    request: Request,
    db: DbDep,
    current_user: CustomerDep,
) -> None:
    """
    Deletes the active UserSession row and records a logout audit event.
    The session token becomes immediately invalid.

    Args:
    ----
        request: Incoming HTTP request (used to extract the client IP for audit).
        db: Injected database session.
        current_user: Authenticated customer resolved by CustomerDep.

    """
    await auth_service.logout(db=db, request=request, user=current_user)


# ── Admin ───
@admin_auth_router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate an admin user and create a server-side session",
)
async def admin_login(
    body: LoginRequest,
    request: Request,
    db: DbDep,
) -> LoginResponse:
    """
    Validates admin credentials (bcrypt), enforces IP policy if registered_ip
    is set, creates or replaces the active UserSession, and returns a session token.

    Args:
    ----
        body: JSON body containing email and password.
        request: Incoming HTTP request (used to extract the client IP).
        db: Injected database session.

    Returns:
    -------
        A LoginResponse with the opaque session_token and its expiry time.

    Raises:
    ------
        HTTPException: 401 if credentials are invalid.
        HTTPException: 403 if the request IP does not match registered_ip.

    """
    session, raw_token = await auth_service.login(
        db=db,
        request=request,
        email=body.email,
        password=body.password,
        role=UserRole.admin,
    )
    return LoginResponse(session_token=raw_token, expires_at=session.expires_at)


@admin_auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate the admin session",
)
async def admin_logout(
    request: Request,
    db: DbDep,
    current_user: AdminDep,
) -> None:
    """
    Deletes the active UserSession row and records a logout audit event.
    The session token becomes immediately invalid.

    Args:
    ----
        request: Incoming HTTP request (used to extract the client IP for audit).
        db: Injected database session.
        current_user: Authenticated admin resolved from the session token.

    """
    await auth_service.logout(db=db, request=request, user=current_user)
