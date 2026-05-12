"""Transaction ORM model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TransactionType(str, PyEnum):
    """Payment routing type."""

    national = "national"
    international = "international"


class TransactionMethod(str, PyEnum):
    """Payment method."""

    debit = "debit"
    credit = "credit"


class TransactionStatus(str, PyEnum):
    """
    Transaction lifecycle status. Customer-facing endpoints never mutate
    status directly.
    """

    pending = "pending"
    completed = "completed"
    failed = "failed"
    scheduled = "scheduled"
    processing = "processing"  # transient: optimistic lock during scheduled execution


class Transaction(Base):
    """
    Immutable financial transaction record. Once persisted, no customer-facing
    endpoint may issue UPDATE or DELETE against this table. Status transitions are
    performed exclusively by internal actors.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        Index("ix_transactions_status_scheduled_for", "status", "scheduled_for"),
        Index(
            "ix_transactions_origin_account_created_at", "origin_account", "created_at"
        ),
        Index("ix_transactions_status_type", "status", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_card: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cards.id", ondelete="RESTRICT"), nullable=False
    )
    origin_account: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    destination_account: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    method: Mapped[TransactionMethod] = mapped_column(
        Enum(TransactionMethod), nullable=False
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus),
        nullable=False,
        default=TransactionStatus.pending,
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=True,
        comment="References the original transaction when this is a reversal.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(tz=UTC).replace(tzinfo=None),
    )

    # Relationships
    card: Mapped["Card"] = relationship(  # type: ignore[name-defined] # resolved at mapper config
        "Card", foreign_keys=[source_card], back_populates="transactions"
    )
    account: Mapped["Account"] = relationship(  # type: ignore[name-defined]
        "Account",
        foreign_keys=[origin_account],
        back_populates="outgoing_transactions",
    )
    original_transaction: Mapped["Transaction | None"] = relationship(
        "Transaction",
        remote_side="Transaction.id",
        foreign_keys=[reversal_of],
    )
