"""Account ORM model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Account(Base):
    """
    Bank account owned by a customer, with a one-to-one relationship to the
    User model. The balance is stored as DECIMAL(19, 4) to avoid floating-point
    precision errors in financial calculations.
    """

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(19, 4),
        nullable=False,
        default=Decimal("0.0000"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(tz=UTC).replace(tzinfo=None),
    )

    # Relationships
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # resolved at mapper config
        "User", back_populates="account"
    )
    cards: Mapped[list["Card"]] = relationship(  # type: ignore[name-defined]
        "Card", back_populates="account", cascade="all, delete-orphan"
    )
    outgoing_transactions: Mapped[list["Transaction"]] = relationship(  # type: ignore[name-defined]
        "Transaction",
        foreign_keys="Transaction.origin_account",
        back_populates="account",
    )
