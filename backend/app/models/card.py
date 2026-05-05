"""Card ORM model."""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CardType(str, PyEnum):
    """Payment card type — determines balance-check business rules."""

    debit = "debit"
    credit = "credit"


class Card(Base):
    """
    Payment card linked to a bank account.

    The card_type drives the transaction processing decision tree:
    debit cards require a balance check; credit cards do not.
    The method is denormalized into each Transaction row at creation
    time so the audit record is self-contained even if the card changes.
    """

    __tablename__ = "cards"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    card_type: Mapped[CardType] = mapped_column(Enum(CardType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now(tz=UTC)
    )

    # Relationships
    account: Mapped["Account"] = relationship(  # type: ignore[name-defined]  # resolved at mapper config
        "Account", back_populates="cards"
    )
    transactions: Mapped[list["Transaction"]] = relationship(  # type: ignore[name-defined]
        "Transaction",
        foreign_keys="Transaction.source_card",
        back_populates="card",
    )
