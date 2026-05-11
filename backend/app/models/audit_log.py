"""
Audit log and user session ORM models.
- AuditLog: Is append-only no updates or deletes issued.
- UserSession: Enforces a one-active-session-per-user policy.
- SessionHistory: Append-only audit trail of all session lifecycle events.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLogAction(str, PyEnum):
    """Audit log action types for backoffice authentication events."""

    login = "login"
    logout = "logout"
    login_failed = "login_failed"


class SessionEvent(str, PyEnum):
    """Lifecycle events recorded in the session history table."""

    login = "login"
    logout = "logout"
    expired = "expired"


class UserSession(Base):
    """
    Active session for a backoffice staff user. Enforces a single active
    session per admin user (UNIQUE on user_id) and is upserted on each successful login.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_sessions_user_id"),
        Index("ix_sessions_token_hash", "token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(tz=UTC).replace(tzinfo=None),
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
        DateTime,
        nullable=False,
        default=lambda: datetime.now(tz=UTC).replace(tzinfo=None),
    )

    # Relationships
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="audit_logs"
    )


class SessionHistory(Base):
    """
    Append-only audit trail of session lifecycle events.
    A row is inserted on login, logout, and session expiry so that the
    full session history of every user can be queried for compliance.
    This table is never updated or deleted.

    Columns:
      - user_id:     Who the session belonged to.
      - event:       login | logout | expired.
      - token_hash:  SHA-256 of the session token, enabling correlation with
                     other systems that store the same digest.
      - ip_address:  Client IP at the time of the event (nullable for expiry).
      - occurred_at: Wall-clock time of the event (UTC, tzinfo stripped).
    """

    __tablename__ = "session_history"
    __table_args__ = (Index("ix_session_history_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    event: Mapped[SessionEvent] = mapped_column(Enum(SessionEvent), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(tz=UTC).replace(tzinfo=None),
    )

    # Relationships
    user: Mapped["User"] = relationship(  # type: ignore[name-defined]
        "User", back_populates="session_history"
    )
