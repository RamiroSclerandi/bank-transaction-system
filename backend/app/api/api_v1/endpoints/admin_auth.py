"""
Admin authentication lifecycle endpoints. These endpoints manage the full
auth lifecycle for BCS staff:
  - POST /admin/auth/login   — validate credentials, create server-side session
  - POST /admin/auth/logout  — invalidate session, record audit event

Flow:
    1. Frontend calls POST /admin/auth/login with email + password.
       → Backend validates credentials (bcrypt), checks IP policy,
         creates UserSession, logs login, returns opaque session_token.
    2. Frontend attaches the token to all subsequent requests as:
         Authorization: Bearer <session_token>
    3. AdminDep resolves the token → session → user on every protected endpoint.
    4. Frontend calls POST /admin/auth/logout.
       → Backend deletes UserSession, logs logout.
"""

from fastapi import APIRouter, Request, status

from app.deps import AdminDep, DbDep
from app.schemas.audit_log import LoginRequest, LoginResponse
from app.services import admin_service

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate an admin user and create a server-side session",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: DbDep,
) -> LoginResponse:
    """
    Validates email/password against the database (bcrypt), enforces IP
    policy if registered_ip is set, creates or replaces the active
    UserSession,  records a login audit event and issues a session token.

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
    session, raw_token = await admin_service.login(
        db=db,
        request=request,
        email=body.email,
        password=body.password,
    )
    return LoginResponse(
        session_token=raw_token,
        expires_at=session.expires_at,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Invalidate the admin session",
)
async def logout(
    request: Request,
    db: DbDep,
    current_user: AdminDep,
) -> None:
    """
    Manage the logout process by deleting the active UserSession row and recording
    a logout audit event. The session token becomes immediately invalid;
    any subsequent request using it will receive 401.

    Args:
    ----
        request: Incoming HTTP request (used to extract the client IP for audit).
        db: Injected database session.
        current_user: Authenticated admin resolved from the session token.

    """
    await admin_service.logout(db=db, request=request, user=current_user)
