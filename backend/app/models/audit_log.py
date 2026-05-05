"""
Audit log and user session ORM models.
- AuditLog: Is append-only no updates or deletes issued.
- UserSession: Enforces a one-active-session-per-admin-user policy.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLogAction(str, PyEnum):
    """Audit log action types for backoffice authentication events."""

    login = "login"
    logout = "logout"
    login_failed = "login_failed"


class UserSession(Base):
    """
    Active session for a backoffice staff user. Enforces a single active
    session per admin user (UNIQUE on user_id) and is upserted on each successful login.
    """

    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_sessions_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now(tz=UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]  # resolved at mapper config
        "User", back_populates="sessions"
    )


class AuditLog(Base):
    """
    Append-only log of backoffice staff authentication events.
    Each login to the monitoring system must produce one AuditLog record.
    This table is never updated or deleted — it is a permanent audit trail.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    action: Mapped[AuditLogAction] = mapped_column(Enum(AuditLogAction), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now(tz=UTC)
    )

    # Relationships
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="audit_logs"
    )
