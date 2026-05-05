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
