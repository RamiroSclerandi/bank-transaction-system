"""
Unified authentication endpoints for all user roles.
  - POST /auth/register     — register a new customer
  - POST /auth/login        — customer login
  - POST /auth/logout       — customer logout
  - POST /admin/auth/register — create a new admin user (admin-only)
  - POST /admin/auth/login  — admin login
  - POST /admin/auth/logout — admin logout
"""

from fastapi import APIRouter, Request, status

from app.core.rate_limit import limiter
from app.deps import AdminDep, CustomerDep, DbDep
from app.models.user import UserRole
from app.schemas.account import AccountRead
from app.schemas.audit_log import LoginRequest, LoginResponse
from app.schemas.user import (
    AdminUserCreate,
    CustomerRegistrationResponse,
    CustomerUserCreate,
    UserReadAdmin,
    UserReadCustomer,
)
from app.services import auth_service, user_service

customer_auth_router = APIRouter(prefix="/auth", tags=["customer-auth"])
admin_auth_router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


# ── Customer ───
@customer_auth_router.post(
    "/register",
    response_model=CustomerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer",
)
@limiter.limit("5/minute")  # type: ignore[reportUntypedFunctionDecorator]
async def customer_register(
    body: CustomerUserCreate,
    request: Request,
    db: DbDep,
) -> CustomerRegistrationResponse:
    """
    Create a new customer user and an associated bank account.
    No session is created here — call POST /auth/login to obtain a token.

    Args:
    ----
        body: Registration payload (personal data + password).
        request: Incoming HTTP request.
        db: Injected database session.

    Returns:
    -------
        A CustomerRegistrationResponse with user data and account data.

    Raises:
    ------
        HTTPException: 409 if the email is already registered.

    """
    user, account = await user_service.register_customer(db=db, data=body)
    return CustomerRegistrationResponse(
        user=UserReadCustomer.model_validate(user),
        account=AccountRead.model_validate(account),
    )


@customer_auth_router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate a customer and create a server-side session",
)
@limiter.limit("10/minute")  # type: ignore[reportUntypedFunctionDecorator]
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
@limiter.limit("5/minute")  # type: ignore[reportUntypedFunctionDecorator]
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


@admin_auth_router.post(
    "/register",
    response_model=UserReadAdmin,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new admin user (admin-only)",
)
@limiter.limit("3/minute")  # type: ignore[reportUntypedFunctionDecorator]
async def admin_register(
    body: AdminUserCreate,
    request: Request,
    db: DbDep,
    _current_admin: AdminDep,
) -> UserReadAdmin:
    """
    Create a new admin user. Only accessible by authenticated admins.
    No session is created — the new admin must call POST /admin/auth/login.

    Args:
    ----
        body: New admin registration payload.
        request: Incoming HTTP request (required by rate limiter).
        db: Injected database session.
        _current_admin: Authenticated admin (session validation only).

    Returns:
    -------
        The newly created admin user.

    Raises:
    ------
        HTTPException: 409 if the email is already registered.

    """
    user = await user_service.create_admin(db=db, data=body)
    return UserReadAdmin.model_validate(user)
