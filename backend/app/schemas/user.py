"""Pydantic schemas for User resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole
from app.schemas.account import AccountRead


class UserBase(BaseModel):
    """Shared fields for user schemas."""

    name: str = Field(..., min_length=1, max_length=255)
    role: UserRole


class UserRead(UserBase):
    """
    User resource returned to callers. Email, phone, dni) are intentionally
    excluded from this response schema to minimise exposure in API responses and logs.
    """

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserReadAdmin(UserBase):
    """
    Extended user schema for admin-only responses (includes PII).
    Only returned on admin-authenticated routes; never logged.
    """

    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminUserCreate(BaseModel):
    """
    Payload for POST /admin/users — create a new backoffice admin user.
    Only existing admins can call this endpoint.
    """

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    national_id: int = Field(..., gt=0)
    phone: int = Field(..., gt=0)
    registered_ip: str | None = Field(
        default=None,
        description=(
            "If set, logins from any other IP will be rejected. "
            "Useful for locking admin access to the office network."
        ),
    )


class UserReadCustomer(BaseModel):
    """Public-facing schema for customer responses."""

    id: uuid.UUID
    name: str
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerUserCreate(BaseModel):
    """
    Payload for POST /auth/register — register a new customer.
    Creates the user and an associated bank account in a single atomic operation.
    """

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    national_id: int = Field(..., gt=0)
    phone: int = Field(..., gt=0)
    registered_ip: str | None = Field(
        default=None,
        description=(
            "If set, logins from any other IP will be rejected. "
            "Useful for locking account access to a specific network."
        ),
    )


class CustomerRegistrationResponse(BaseModel):
    """
    Returned after a successful POST /auth/register.
    Includes the created user, the associated bank account, the session token,
    and its expiry time so the client can start making authenticated requests
    immediately without a separate login step.
    """

    user: UserReadCustomer
    account: AccountRead
    session_token: str
    expires_at: datetime

    model_config = {"from_attributes": True}
