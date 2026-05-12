"""Pydantic schemas for Card resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.card import CardType


class CardInput(BaseModel):
    """
    Card details provided by the customer at transaction creation time.
    The card is looked up by HMAC of the PAN and reused if it already exists,
    or created on first use (get-or-create semantics).
    The CVV is accepted for API completeness but is never stored in any form
    (PCI DSS requirement).
    """

    number: str = Field(
        ...,
        pattern=r"^\d{4}-\d{4}-\d{4}-\d{4}$",
        description="16-digit card number in XXXX-XXXX-XXXX-XXXX format.",
    )
    expiration_month: int = Field(..., ge=1, le=12)
    expiration_year: int = Field(
        ...,
        ge=26,
        le=99,
        description="Last 2 digits of the expiration year (e.g. 28 for 2028).",
    )
    cvv: str = Field(
        ...,
        pattern=r"^\d{3}$",
        description="3-digit security code. Validated but never stored.",
    )
    card_type: CardType

    @model_validator(mode="after")
    def card_must_not_be_expired(self) -> "CardInput":
        """Reject cards whose expiry month/year is already in the past."""
        now = datetime.now()
        current_year = now.year % 100
        current_month = now.month
        if self.expiration_year < current_year or (
            self.expiration_year == current_year
            and self.expiration_month < current_month
        ):
            raise ValueError("Card is expired.")
        return self


class CardRead(BaseModel):
    """
    Card resource returned to callers.
    Only the last 4 digits are exposed, both directly via
    `number_last4` and in masked display form via `number_masked`.
    The full PAN and CVV are never returned.
    """

    id: uuid.UUID
    account_id: uuid.UUID
    card_type: CardType
    number_last4: str
    expiration_month: int
    expiration_year: int
    created_at: datetime

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def number_masked(self) -> str:
        """Return a masked card number showing only the last 4 digits."""
        return f"****-****-****-{self.number_last4}"
