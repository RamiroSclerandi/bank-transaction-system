"""Pydantic schemas for Transaction resources."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.transaction import TransactionStatus, TransactionType


class TransactionCreate(BaseModel):
    """
    Payload for creating a new transaction. The `method` is NOT provided
    by the caller — it is derived by the service from the source card's
    card_type and denormalized into the record.  The `origin_account` is also
    derived from the source card's account.
    """

    source_card: uuid.UUID = Field(..., description="UUID of the card to charge.")
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


class TransactionProcessInternal(BaseModel):
    """
    Request body sent by the Lambda worker to trigger scheduled processing.
    This endpoint is IAM-authenticated and not exposed to customers.
    """

    model_config = {"from_attributes": True}

    pass  # transaction_id is provided as a path parameter


class WebhookUpdate(BaseModel):
    """
    Payload from the external international payment processor.
    Called on the internal webhook endpoint after the external processor
    completes or rejects an international payment.
    """

    status: TransactionStatus = Field(
        ...,
        description="Final status: 'completed' or 'failed'.",
    )
    external_reference: str | None = Field(
        default=None,
        max_length=255,
        description="External processor's reference ID for correlation.",
    )

    @field_validator("status")
    @classmethod
    def status_must_be_terminal(cls, v: TransactionStatus) -> TransactionStatus:
        """Ensure the webhook only sets terminal statuses."""
        if v not in (TransactionStatus.completed, TransactionStatus.failed):
            raise ValueError("Webhook status must be 'completed' or 'failed'.")
        return v


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
