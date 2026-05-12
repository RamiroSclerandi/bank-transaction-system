"""Card ORM model."""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CardType(str, PyEnum):
    """Payment card type — determines balance-check business rules."""

    debit = "debit"
    credit = "credit"


class Card(Base):
    """
    Payment card linked to a bank account. They are retrieved from the DB
    or created on a transaction. There is no upper limit on the number
    of cards per account.
    The card_type drives the transaction processing decision tree:
    debit cards require a balance check; credit cards do not.
    The method is denormalized into each Transaction row at creation
    time so the audit record is self-contained even if the card changes.

    Security notes (PCI DSS):
      - `number_hmac` is an HMAC-SHA256 digest of the PAN digits used for
        lookup. The raw PAN is never persisted.
      - `number_last4` stores the last 4 digits in plain text for display.
      - CVV is never stored in any form (PCI DSS requirement).
    """

    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint(
            "expiration_month >= 1 AND expiration_month <= 12",
            name="ck_cards_expiration_month",
        ),
        CheckConstraint(
            "expiration_year >= 26",
            name="ck_cards_expiration_year",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    card_type: Mapped[CardType] = mapped_column(Enum(CardType), nullable=False)
    # HMAC-SHA256 of the raw PAN digits (no hyphens); globally unique; used for lookup
    number_hmac: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # Last 4 digits of the PAN in plain text; safe to expose in API responses
    number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    expiration_month: Mapped[int] = mapped_column(Integer, nullable=False)
    expiration_year: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(tz=UTC).replace(tzinfo=None),
    )

    # Relationships
    account: Mapped["Account"] = relationship(  # type: ignore[name-defined]
        "Account", back_populates="cards"
    )
    transactions: Mapped[list["Transaction"]] = relationship(  # type: ignore[name-defined]
        "Transaction",
        foreign_keys="Transaction.source_card",
        back_populates="card",
    )
