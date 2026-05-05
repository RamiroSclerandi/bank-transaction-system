"""Pydantic schemas for AuditLog and UserSession resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr

from app.models.audit_log import AuditLogAction


class AuditLogRead(BaseModel):
    """Audit log entry returned to admin callers."""

    id: uuid.UUID
    user_id: uuid.UUID
    action: AuditLogAction
    ip_address: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}


class UserSessionRead(BaseModel):
    """Active session record returned to admin callers."""

    id: uuid.UUID
    user_id: uuid.UUID
    ip_address: str | None
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    """Credentials submitted to POST /admin/auth/login."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """
    Returned to the client after a successful admin login.
    The session_token must be sent on every subsequent request as:
        Authorization: Bearer <session_token>
    """

    session_token: str
    expires_at: datetime

    model_config = {"from_attributes": True}
