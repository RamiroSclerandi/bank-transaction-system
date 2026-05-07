"""
Customer registration endpoint.
  - POST /auth/register  — create customer user + bank account + issue session token

Login and logout are handled by the unified auth router (auth.py).
"""

from fastapi import APIRouter, Request, status

from app.core.rate_limit import limiter
from app.deps import DbDep
from app.schemas.account import AccountRead
from app.schemas.user import (
    CustomerRegistrationResponse,
    CustomerUserCreate,
    UserReadCustomer,
)
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["customer-auth"])


@router.post(
    "/register",
    response_model=CustomerRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer and open a session",
)
@limiter.limit("3/hour")  # type: ignore[reportUntypedFunctionDecorator]
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
    user, account, session, raw_token = await user_service.register_customer(
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
