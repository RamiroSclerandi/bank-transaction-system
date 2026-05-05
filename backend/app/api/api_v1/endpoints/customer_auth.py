"""
Customer authentication lifecycle endpoints. These endpoints manage the full
auth lifecycle for bank customers:
  - POST /auth/register  — create account + issue session token
  - POST /auth/login     — validate credentials, create server-side session
  - POST /auth/logout    — invalidate session, record audit event

Flow:
    1. Customer calls POST /auth/register with personal data + password.
       → Backend creates User (role=customer) + Account atomically,
         opens a session, and returns the opaque session_token.
    2. Returning customers call POST /auth/login with email + password.
       → Backend validates credentials (bcrypt), checks IP policy,
         creates UserSession, logs login, returns opaque session_token.
    3. Customer attaches the token to all subsequent requests as:
         Authorization: Bearer <session_token>
    4. CustomerDep resolves the token → session → user on every protected endpoint.
    5. Customer calls POST /auth/logout.
       → Backend deletes UserSession, logs logout.
"""

from fastapi import APIRouter, Request, status

from app.deps import CustomerDep, DbDep
from app.schemas.account import AccountRead
from app.schemas.audit_log import LoginRequest, LoginResponse
from app.schemas.user import (
    CustomerRegistrationResponse,
    CustomerUserCreate,
    UserReadCustomer,
)
from app.services import customer_service

router = APIRouter(prefix="/auth", tags=["customer-auth"])


@router.post(
    "/register",
    response_model=CustomerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer and open a session",
)
async def register(
    body: CustomerUserCreate,
    request: Request,
    db: DbDep,
) -> CustomerRegistrationResponse:
    """
    Create a new customer user and an associated bank account.
    The user, account, and session are created atomically. The returned
    session_token can be used immediately for authenticated requests.

    Args:
    ----
        body: Registration payload (personal data + password).
        request: Incoming HTTP request (used to extract the client IP).
        db: Injected database session.

    Returns:
    -------
        A CustomerRegistrationResponse with user data, account data,
        the opaque session_token, and its expiry time.

    Raises:
    ------
        HTTPException: 409 if the email is already registered.

    """
    user, account, session, raw_token = await customer_service.register(
        db=db,
        request=request,
        data=body,
    )
    return CustomerRegistrationResponse(
        user=UserReadCustomer.model_validate(user),
        account=AccountRead.model_validate(account),
        session_token=raw_token,
        expires_at=session.expires_at,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate a customer and create a server-side session",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: DbDep,
) -> LoginResponse:
    """
    Validate customer credentials and issue a session token.

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
    session, raw_token = await customer_service.login(
        db=db,
        request=request,
        email=body.email,
        password=body.password,
    )
    return LoginResponse(session_token=raw_token, expires_at=session.expires_at)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate the current customer session",
)
async def logout(
    request: Request,
    db: DbDep,
    current_user: CustomerDep,
) -> None:
    """
    Manage the logout process by deleting the active UserSession row and recording
    a logout audit event. The session token becomes immediately invalid;
    any subsequent request using it will receive 401.

    Args:
    ----
        request: Incoming HTTP request (used to extract the client IP).
        db: Injected database session.
        current_user: Authenticated customer resolved by CustomerDep.

    """
    await customer_service.logout(db=db, request=request, user=current_user)
