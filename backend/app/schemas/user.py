"""Pydantic schemas for User resources."""

import ipaddress
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from utils.validators import EmailStr

from app.models.user import UserRole
from app.schemas.account import AccountRead


def _validate_ip(v: str | None) -> str | None:
    """Validate that the value is a valid IPv4 or IPv6 address."""
    if v is None:
        return v
    try:
        ipaddress.ip_address(v)
    except ValueError:
        raise ValueError(f"'{v}' is not a valid IP address")
    return v


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

    _validate_registered_ip = field_validator("registered_ip", mode="before")(
        _validate_ip
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

    _validate_registered_ip = field_validator("registered_ip", mode="before")(
        _validate_ip
    )


class CustomerRegistrationResponse(BaseModel):
    """
    Returned after a successful POST /auth/register.
    Includes the created user and the associated bank account.
    A session token is obtained separately via POST /auth/login.
    """

    user: UserReadCustomer
    account: AccountRead

    model_config = {"from_attributes": True}
