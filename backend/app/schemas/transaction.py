"""Pydantic schemas for Transaction resources."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.transaction import TransactionStatus, TransactionType
from app.schemas.card import CardInput


class TransactionCreate(BaseModel):
    """
    Payload for creating a new transaction.

    `card` contains the full card details used to identify or create the
    payment card (get-or-create semantics). The `method` (debit/credit) is
    derived from the card_type and denormalized into the transaction record.
    The `origin_account` is derived from the card's owning account.
    """

    card: CardInput = Field(..., description="Card details used for this transaction.")
    destination_account: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Target account UUID (national) or IBAN/SWIFT (international).",
    )
    amount: Decimal = Field(..., gt=Decimal("0"), decimal_places=4)
    type: TransactionType
    scheduled_for: datetime | None = Field(
        default=None,
        description="If set to a future datetime, the transaction is scheduled.",
    )
    reversal_of: uuid.UUID | None = Field(
        default=None,
        description="Reference to the original transaction if this is a reversal.",
    )

    @field_validator("scheduled_for", mode="after")
    @classmethod
    def scheduled_for_must_be_future(cls, v: datetime | None) -> datetime | None:
        """Reject scheduled_for values that are not in the future."""
        if v is not None:
            now = datetime.now(tz=UTC).replace(tzinfo=None)
            # Normalize aware datetimes to UTC before storing/comparing as naive UTC
            v_normalized = (
                v.astimezone(UTC).replace(tzinfo=None) if v.tzinfo is not None else v
            )
            if v_normalized <= now:
                raise ValueError("scheduled_for must be a future datetime")
            return v_normalized
        return v


class TransactionProcessInternal(BaseModel):
    """
    Request body sent by the Lambda worker to trigger scheduled processing.
    This endpoint is IAM-authenticated and not exposed to customers.
    """

    model_config = {"from_attributes": True}

    pass  # transaction_id is provided as a path parameter


class TransactionRead(BaseModel):
    """Transaction resource returned to callers."""

    id: uuid.UUID
    source_card: uuid.UUID
    origin_account: uuid.UUID
    destination_account: str
    amount: Decimal
    type: TransactionType
    method: str
    status: TransactionStatus
    scheduled_for: datetime | None
    reversal_of: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionListFilters(BaseModel):
    """Query parameters for filtering the admin transaction list."""

    user_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    status: TransactionStatus | None = None
    type: TransactionType | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
