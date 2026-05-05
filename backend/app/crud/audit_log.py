"""CRUD operations for AuditLog and UserSession."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog, AuditLogAction, UserSession


class CRUDAuditLog:
    """
    Data access layer for the AuditLog model is append-only. No update or
    delete operations are provided.
    """

    async def create(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        action: AuditLogAction,
        ip_address: str | None = None,
    ) -> AuditLog:
        """
        Append a new audit log entry.

        Args:
        ----
            db: Active async database session.
            user_id: The user who performed the action.
            action: The authentication event type.
            ip_address: Optional source IP of the request.

        Returns:
        -------
            The newly created AuditLog instance.

        """
        entry = AuditLog(
            user_id=user_id,
            action=action,
            ip_address=ip_address,
        )
        db.add(entry)
        await db.flush()
        await db.refresh(entry)
        return entry


class CRUDUserSession:
    """Data access layer for the UserSession model."""

    async def upsert(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None = None,
    ) -> None:
        """
        Upsert the active session for a staff user. Enforces the
        one-active-session-per-user policy by replacing the existing row
        if one exists (PostgreSQL INSERT ... ON CONFLICT DO UPDATE).

        Args:
        ----
            db: Active async database session.
            user_id: The staff user's UUID.
            token_hash: SHA-256 hex digest of the bearer token.
            expires_at: Token expiry datetime.
            ip_address: Optional source IP.

        """
        stmt = (
            pg_insert(UserSession)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                ip_address=ip_address,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                    "ip_address": ip_address,
                    "created_at": datetime.now(tz=UTC),
                },
            )
        )
        await db.execute(stmt)

    async def get_by_user_id(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
    ) -> UserSession | None:
        """
        Fetch the active session for a staff user, if any.

        Args:
        ----
            db: Active async database session.
            user_id: The staff user's UUID.

        Returns:
        -------
            The UserSession instance or None if no session exists.

        """
        result = await db.execute(
            select(UserSession).where(UserSession.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_token_hash(
        self,
        db: AsyncSession,
        *,
        token_hash: str,
    ) -> UserSession | None:
        """
        Fetch an active session by its token hash. It is used by the auth
        dependency to resolve a Bearer token to a session without needing
        the user_id up front.

        Args:
        ----
            db: Active async database session.
            token_hash: SHA-256 hex digest of the raw session token.

        Returns:
        -------
            The UserSession instance or None if no matching session exists.

        """
        result = await db.execute(
            select(UserSession).where(UserSession.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def delete(
        self,
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
    ) -> None:
        """
        Delete the active session for a staff user (logout action).

        Args:
        ----
            db: Active async database session.
            user_id: The staff user's UUID.

        """
        session = await self.get_by_user_id(db, user_id=user_id)
        if session is not None:
            await db.delete(session)


crud_audit_log = CRUDAuditLog()
crud_user_session = CRUDUserSession()
