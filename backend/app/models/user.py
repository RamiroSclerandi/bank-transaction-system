"""User ORM model."""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import BigInteger, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, PyEnum):
    """User role within the system."""

    admin = "admin"
    customer = "customer"


class User(Base):
    """
    Registered user — either a bank customer or a backoffice staff member.
    PII columns (email, phone, national_id) must never appear in application logs.
    The `role` field is the authoritative source for RBAC.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # PII — never log
    national_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    registered_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now(tz=UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.now(tz=UTC),
        onupdate=datetime.now(tz=UTC),
    )

    # Relationships
    account: Mapped["Account"] = relationship(  # type: ignore[name-defined]  # resolved at mapper config
        "Account", back_populates="user", uselist=False
    )
    sessions: Mapped[list["UserSession"]] = relationship(  # type: ignore[name-defined]
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # type: ignore[name-defined]
        "AuditLog", back_populates="user"
    )
