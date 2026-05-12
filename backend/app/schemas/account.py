"""Pydantic schemas for Account resources."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AccountRead(BaseModel):
    """Account resource returned to callers."""

    id: uuid.UUID
    user_id: uuid.UUID
    balance: Decimal = Field(..., description="Current balance in DECIMAL(19,4).")
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountAddBalance(BaseModel):
    """Payload for POST /accounts/add-balance — adds balance to the user's account."""

    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        decimal_places=4,
        description="Amount to add. Must be positive.",
    )


class AdminAccountCreate(BaseModel):
    """Payload for POST /admin/accounts — create a bank account for a user."""

    user_id: uuid.UUID = Field(
        ..., description="UUID of the user to create an account for."
    )
