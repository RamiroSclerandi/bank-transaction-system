"""
Unit tests for CRUDAuditLog, CRUDUserSession, and CRUDSessionHistory.

Uses AsyncMock sessions — no real DB.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.audit_log import CRUDAuditLog, CRUDSessionHistory, CRUDUserSession
from app.models.audit_log import (
    AuditLogAction,
    SessionEvent,
    UserSession,
)
from sqlalchemy.exc import IntegrityError

# ── CRUDAuditLog ──────────────────────────────────────────────────────────────


class TestCRUDAuditLogCreate:
    """Tests for CRUDAuditLog.create."""

    @pytest.mark.asyncio
    async def test_creates_audit_entry(self) -> None:
        """create() adds an AuditLog entry, flushes and refreshes it."""
        crud = CRUDAuditLog()
        user_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await crud.create(
            db,
            user_id=user_id,
            action=AuditLogAction.login,
            ip_address="1.2.3.4",
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.user_id == user_id
        assert result.action == AuditLogAction.login
        assert result.ip_address == "1.2.3.4"

    @pytest.mark.asyncio
    async def test_create_audit_log_integrity_error_propagates(self) -> None:
        """create() propagates IntegrityError when flush fails (e.g. FK violation)."""
        crud = CRUDAuditLog()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock(side_effect=IntegrityError(None, None, None))

        with pytest.raises(IntegrityError):
            await crud.create(
                db,
                user_id=uuid.uuid4(),
                action=AuditLogAction.login,
                ip_address="1.2.3.4",
            )


# ── CRUDUserSession ───────────────────────────────────────────────────────────


class TestCRUDUserSessionGetByTokenHash:
    """Tests for CRUDUserSession.get_by_token_hash."""

    @pytest.mark.asyncio
    async def test_returns_session_when_found(self) -> None:
        """get_by_token_hash() returns the session when found."""
        crud = CRUDUserSession()
        session = MagicMock(spec=UserSession)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = session
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_by_token_hash(db, token_hash="deadbeef")  # noqa: S106

        assert result is session

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        """get_by_token_hash() returns None when no session is found."""
        crud = CRUDUserSession()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        result = await crud.get_by_token_hash(db, token_hash="unknown")  # noqa: S106

        assert result is None


class TestCRUDUserSessionUpsert:
    """Tests for CRUDUserSession.upsert."""

    @pytest.mark.asyncio
    async def test_upsert_executes_statement(self) -> None:
        """upsert() calls db.execute once with the INSERT ... ON CONFLICT statement."""
        crud = CRUDUserSession()
        db = AsyncMock()
        db.execute = AsyncMock()

        await crud.upsert(
            db,
            user_id=uuid.uuid4(),
            token_hash="abc123",  # noqa: S106
            expires_at=datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(hours=1),
            ip_address="1.2.3.4",
        )

        db.execute.assert_awaited_once()


class TestCRUDUserSessionDelete:
    """Tests for CRUDUserSession.delete."""

    @pytest.mark.asyncio
    async def test_delete_removes_existing_session(self) -> None:
        """delete() calls db.delete when a session is found."""
        crud = CRUDUserSession()
        user_id = uuid.uuid4()
        existing = MagicMock(spec=UserSession)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=result_mock)

        await crud.delete(db, user_id=user_id)

        db.delete.assert_awaited_once_with(existing)

    @pytest.mark.asyncio
    async def test_delete_is_noop_when_no_session(self) -> None:
        """delete() does nothing when no session exists for user_id."""
        crud = CRUDUserSession()
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        await crud.delete(db, user_id=uuid.uuid4())

        db.delete.assert_not_awaited()


# ── CRUDSessionHistory ────────────────────────────────────────────────────────


class TestCRUDSessionHistoryCreate:
    """Tests for CRUDSessionHistory.create."""

    @pytest.mark.asyncio
    async def test_creates_session_history_entry(self) -> None:
        """create() adds a SessionHistory record, flushes and refreshes."""
        crud = CRUDSessionHistory()
        user_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await crud.create(
            db,
            user_id=user_id,
            event=SessionEvent.login,
            token_hash="deadbeef",  # noqa: S106
            ip_address="1.2.3.4",
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        assert result.user_id == user_id
        assert result.event == SessionEvent.login
