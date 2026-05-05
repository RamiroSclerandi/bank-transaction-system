"""Covers the session lifecycle (register_session, logout, require_active_session)
and the data-access helpers (get_transaction, list_transactions) in isolation
by mocking all CRUD dependencies."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.audit_log import AuditLogAction, UserSession
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionListFilters
from app.services import admin_service


# Helpers
def _mock_request(ip: str = "1.2.3.4") -> MagicMock:
    """Build a minimal mock Request with a configurable client IP."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = ip
    # headers.get returns a Bearer token for any key
    request.headers.get = MagicMock(return_value="Bearer test-token")
    return request


def _make_session(
    user_id: uuid.UUID,
    expires_at: datetime | None = None,
) -> MagicMock:
    """Build a mock UserSession that expires 1 hour from now by default."""
    session = MagicMock(spec=UserSession)
    session.id = uuid.uuid4()
    session.user_id = user_id
    session.token_hash = "deadbeef"
    session.ip_address = "1.2.3.4"
    session.created_at = datetime.now(UTC).replace(tzinfo=None)
    session.expires_at = expires_at or (
        datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(hours=1)
    )
    return session


# TestLogin
class TestLogin:
    """Tests for admin_service.login."""

    @pytest.mark.asyncio
    async def test_no_registered_ip_creates_session_and_logs_login(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """When registered_ip is None, any IP is accepted and session is created."""
        assert admin_user.registered_ip is None
        request = _mock_request(ip="5.6.7.8")
        session = _make_session(admin_user.id)

        with (
            patch("app.services.admin_service.crud_audit_log") as mock_audit,
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
            patch("app.services.admin_service.crud_user") as mock_crud_user,
            patch("app.services.admin_service.verify_password", return_value=True),
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.upsert = AsyncMock()
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
            mock_crud_user.get_by_email = AsyncMock(return_value=admin_user)

            result_session, raw_token = await admin_service.login(
                db=mock_db, request=request, email=admin_user.email, password="secret"
            )

        assert result_session is session
        assert isinstance(raw_token, str) and len(raw_token) > 0
        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login
        assert audit_kwargs["user_id"] == admin_user.id
        mock_session_crud.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_matching_registered_ip_creates_session(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """When registered_ip matches the request IP the session is created normally."""
        admin_user.registered_ip = "10.0.0.1"
        request = _mock_request(ip="10.0.0.1")
        session = _make_session(admin_user.id)

        with (
            patch("app.services.admin_service.crud_audit_log") as mock_audit,
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
            patch("app.services.admin_service.crud_user") as mock_crud_user,
            patch("app.services.admin_service.verify_password", return_value=True),
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.upsert = AsyncMock()
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
            mock_crud_user.get_by_email = AsyncMock(return_value=admin_user)

            result_session, _ = await admin_service.login(
                db=mock_db, request=request, email=admin_user.email, password="secret"
            )

        assert result_session is session
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login

    @pytest.mark.asyncio
    async def test_ip_mismatch_logs_login_failed_and_raises_403(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """When registered_ip does not match the request IP, 403 raised."""
        admin_user.registered_ip = "10.0.0.1"
        request = _mock_request(ip="9.9.9.9")  # different from registered

        with (
            patch("app.services.admin_service.crud_audit_log") as mock_audit,
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
            patch("app.services.admin_service.crud_user") as mock_crud_user,
            patch("app.services.admin_service.verify_password", return_value=True),
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.upsert = AsyncMock()
            mock_crud_user.get_by_email = AsyncMock(return_value=admin_user)

            with pytest.raises(HTTPException) as exc_info:
                await admin_service.login(
                    db=mock_db,
                    request=request,
                    email=admin_user.email,
                    password="secret",
                )

        assert exc_info.value.status_code == 403
        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login_failed
        assert audit_kwargs["ip_address"] == "9.9.9.9"
        # Session must NOT have been created
        mock_session_crud.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_login_ip_is_recorded_on_audit_entry(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """The client IP extracted from the request is stored in the audit log."""
        expected_ip = "203.0.113.42"
        request = _mock_request(ip=expected_ip)
        session = _make_session(admin_user.id)

        with (
            patch("app.services.admin_service.crud_audit_log") as mock_audit,
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
            patch("app.services.admin_service.crud_user") as mock_crud_user,
            patch("app.services.admin_service.verify_password", return_value=True),
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.upsert = AsyncMock()
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
            mock_crud_user.get_by_email = AsyncMock(return_value=admin_user)

            await admin_service.login(
                db=mock_db, request=request, email=admin_user.email, password="secret"
            )

        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["ip_address"] == expected_ip

    @pytest.mark.asyncio
    async def test_wrong_password_raises_401(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Invalid password must raise 401 without creating a session."""
        request = _mock_request()

        with (
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
            patch("app.services.admin_service.crud_user") as mock_crud_user,
            patch("app.services.admin_service.verify_password", return_value=False),
        ):
            mock_session_crud.upsert = AsyncMock()
            mock_crud_user.get_by_email = AsyncMock(return_value=admin_user)

            with pytest.raises(HTTPException) as exc_info:
                await admin_service.login(
                    db=mock_db,
                    request=request,
                    email=admin_user.email,
                    password="wrong",
                )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_email_raises_401(
        self,
        mock_db: AsyncMock,
    ) -> None:
        """Unknown email must raise 401 without leaking whether the email exists."""
        request = _mock_request()

        with (
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
            patch("app.services.admin_service.crud_user") as mock_crud_user,
            patch("app.services.admin_service.verify_password", return_value=False),
        ):
            mock_session_crud.upsert = AsyncMock()
            mock_crud_user.get_by_email = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await admin_service.login(
                    db=mock_db,
                    request=request,
                    email="nobody@example.com",
                    password="secret",
                )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()


# TestLogout
class TestLogout:
    """Tests for admin_service.logout."""

    @pytest.mark.asyncio
    async def test_logout_writes_audit_and_deletes_session(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Logout must record an audit logout event and delete the session row."""
        request = _mock_request()

        with (
            patch("app.services.admin_service.crud_audit_log") as mock_audit,
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.delete = AsyncMock()

            await admin_service.logout(db=mock_db, request=request, user=admin_user)

        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.logout
        assert audit_kwargs["user_id"] == admin_user.id
        mock_session_crud.delete.assert_awaited_once()
        delete_kwargs = mock_session_crud.delete.call_args.kwargs
        assert delete_kwargs["user_id"] == admin_user.id

    @pytest.mark.asyncio
    async def test_logout_records_ip_in_audit(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Logout audit entry must capture the client IP."""
        request = _mock_request(ip="192.168.1.50")

        with (
            patch("app.services.admin_service.crud_audit_log") as mock_audit,
            patch("app.services.admin_service.crud_user_session") as mock_session_crud,
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.delete = AsyncMock()

            await admin_service.logout(db=mock_db, request=request, user=admin_user)

        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["ip_address"] == "192.168.1.50"


# TestRequireActiveSession
class TestRequireActiveSession:
    """Tests for admin_service.require_active_session."""

    @pytest.mark.asyncio
    async def test_active_non_expired_session_passes(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """A valid, non-expired session must not raise any exception."""
        session = _make_session(admin_user.id)  # expires in 1 hour

        with patch("app.services.admin_service.crud_user_session") as mock_session_crud:
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)

            # Should not raise
            await admin_service.require_active_session(db=mock_db, user=admin_user)

    @pytest.mark.asyncio
    async def test_no_session_raises_401(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """When no session row exists, a 401 must be raised."""
        with patch("app.services.admin_service.crud_user_session") as mock_session_crud:
            mock_session_crud.get_by_user_id = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await admin_service.require_active_session(db=mock_db, user=admin_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_session_raises_401(
        self,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """An expired session must be rejected with a 401."""
        expired_at = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(minutes=5)
        session = _make_session(admin_user.id, expires_at=expired_at)

        with patch("app.services.admin_service.crud_user_session") as mock_session_crud:
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)

            with pytest.raises(HTTPException) as exc_info:
                await admin_service.require_active_session(db=mock_db, user=admin_user)

        assert exc_info.value.status_code == 401


# TestGetTransaction
class TestGetTransaction:
    """Tests for admin_service.get_transaction."""

    @pytest.mark.asyncio
    async def test_returns_transaction_when_found(self, mock_db: AsyncMock) -> None:
        """When the CRUD layer finds the transaction it is returned as-is."""
        tx = MagicMock(spec=Transaction)
        tx.id = uuid.uuid4()

        with patch("app.services.admin_service.crud_transaction") as mock_crud_tx:
            mock_crud_tx.get = AsyncMock(return_value=tx)

            result = await admin_service.get_transaction(
                db=mock_db, transaction_id=tx.id
            )

        assert result is tx

    @pytest.mark.asyncio
    async def test_raises_404_when_not_found(self, mock_db: AsyncMock) -> None:
        """When the CRUD layer returns None a 404 must be raised."""
        with patch("app.services.admin_service.crud_transaction") as mock_crud_tx:
            mock_crud_tx.get = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await admin_service.get_transaction(
                    db=mock_db, transaction_id=uuid.uuid4()
                )

        assert exc_info.value.status_code == 404


# TestListTransactions
class TestListTransactions:
    """Tests for admin_service.list_transactions."""

    @pytest.mark.asyncio
    async def test_returns_list_from_crud(self, mock_db: AsyncMock) -> None:
        """list_transactions must delegate to crud and return the result unchanged."""
        tx1 = MagicMock(spec=Transaction)
        tx2 = MagicMock(spec=Transaction)
        filters = TransactionListFilters(limit=10, offset=0)

        with patch("app.services.admin_service.crud_transaction") as mock_crud_tx:
            mock_crud_tx.list_filtered = AsyncMock(return_value=[tx1, tx2])

            result = await admin_service.list_transactions(db=mock_db, filters=filters)

        assert result == [tx1, tx2]
        mock_crud_tx.list_filtered.assert_awaited_once_with(mock_db, filters=filters)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_matches(self, mock_db: AsyncMock) -> None:
        """list_transactions returns an empty list when no transactions match."""
        filters = TransactionListFilters(limit=10, offset=0)

        with patch("app.services.admin_service.crud_transaction") as mock_crud_tx:
            mock_crud_tx.list_filtered = AsyncMock(return_value=[])

            result = await admin_service.list_transactions(db=mock_db, filters=filters)

        assert result == []
        mock_crud_tx.list_filtered.assert_awaited_once_with(mock_db, filters=filters)
