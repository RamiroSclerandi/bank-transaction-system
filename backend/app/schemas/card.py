"""Pydantic schemas for Card resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.card import CardType


class CardRead(BaseModel):
    """Card resource returned to callers."""

    id: uuid.UUID
    account_id: uuid.UUID
    card_type: CardType
    created_at: datetime

    model_config = {"from_attributes": True}
