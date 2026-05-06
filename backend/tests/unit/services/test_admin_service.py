"""
Covers the session lifecycle (register_session, logout, require_active_session)
and the data-access helpers (get_transaction, list_transactions) in isolation
by mocking all CRUD dependencies.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.audit_log import AuditLogAction
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionListFilters
from app.services import admin_service
from fastapi import HTTPException


# TestLogin
class TestLogin:
    """Tests for admin_service.login."""

    @pytest.mark.asyncio
    @patch("app.services.admin_service.verify_password", return_value=True)
    @patch("app.services.admin_service.crud_user")
    @patch("app.services.admin_service.crud_user_session")
    @patch("app.services.admin_service.crud_audit_log")
    async def test_no_registered_ip_creates_session_and_logs_login(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """When registered_ip is None, any IP is accepted and session is created."""
        assert admin_user.registered_ip is None
        request = mock_request(ip="5.6.7.8")
        session = make_session(admin_user.id)
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
    @patch("app.services.admin_service.verify_password", return_value=True)
    @patch("app.services.admin_service.crud_user")
    @patch("app.services.admin_service.crud_user_session")
    @patch("app.services.admin_service.crud_audit_log")
    async def test_matching_registered_ip_creates_session(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """When registered_ip matches the request IP the session is created normally."""
        admin_user.registered_ip = "10.0.0.1"
        request = mock_request(ip="10.0.0.1")
        session = make_session(admin_user.id)
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
    @patch("app.services.admin_service.verify_password", return_value=True)
    @patch("app.services.admin_service.crud_user")
    @patch("app.services.admin_service.crud_user_session")
    @patch("app.services.admin_service.crud_audit_log")
    async def test_ip_mismatch_logs_login_failed_and_raises_403(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """When registered_ip does not match the request IP, 403 raised."""
        admin_user.registered_ip = "10.0.0.1"
        request = mock_request(ip="9.9.9.9")  # different from registered
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
    @patch("app.services.admin_service.verify_password", return_value=True)
    @patch("app.services.admin_service.crud_user")
    @patch("app.services.admin_service.crud_user_session")
    @patch("app.services.admin_service.crud_audit_log")
    async def test_login_ip_is_recorded_on_audit_entry(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """The client IP extracted from the request is stored in the audit log."""
        expected_ip = "203.0.113.42"
        request = mock_request(ip=expected_ip)
        session = make_session(admin_user.id)
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
    @patch("app.services.admin_service.verify_password", return_value=False)
    @patch("app.services.admin_service.crud_user")
    @patch("app.services.admin_service.crud_user_session")
    async def test_wrong_password_raises_401(
        self,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Invalid password must raise 401 without creating a session."""
        request = mock_request()
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
    @patch("app.services.admin_service.verify_password", return_value=False)
    @patch("app.services.admin_service.crud_user")
    @patch("app.services.admin_service.crud_user_session")
    async def test_unknown_email_raises_401(
        self,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Unknown email must raise 401 without leaking whether the email exists."""
        request = mock_request()
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
    @patch("app.services.admin_service.crud_user_session")
    @patch("app.services.admin_service.crud_audit_log")
    async def test_logout_writes_audit_and_deletes_session(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Logout must record an audit logout event and delete the session row."""
        request = mock_request()
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
    @patch("app.services.admin_service.crud_user_session")
    @patch("app.services.admin_service.crud_audit_log")
    async def test_logout_records_ip_in_audit(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Logout audit entry must capture the client IP."""
        request = mock_request(ip="192.168.1.50")
        mock_audit.create = AsyncMock()
        mock_session_crud.delete = AsyncMock()

        await admin_service.logout(db=mock_db, request=request, user=admin_user)

        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["ip_address"] == "192.168.1.50"


# TestRequireActiveSession
class TestRequireActiveSession:
    """Tests for admin_service.require_active_session."""

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_user_session")
    async def test_active_non_expired_session_passes(
        self,
        mock_session_crud: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        make_session: Callable[..., MagicMock],
    ):
        """A valid, non-expired session must not raise any exception."""
        session = make_session(admin_user.id)  # expires in 1 hour
        mock_session_crud.get_by_user_id = AsyncMock(return_value=session)

        # Should not raise
        await admin_service.require_active_session(db=mock_db, user=admin_user)

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_user_session")
    async def test_no_session_raises_401(
        self,
        mock_session_crud: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
    ):
        """When no session row exists, a 401 must be raised."""
        mock_session_crud.get_by_user_id = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await admin_service.require_active_session(db=mock_db, user=admin_user)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_user_session")
    async def test_expired_session_raises_401(
        self,
        mock_session_crud: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        make_session: Callable[..., MagicMock],
    ):
        """An expired session must be rejected with a 401."""
        expired_at = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(minutes=5)
        session = make_session(admin_user.id, expires_at=expired_at)
        mock_session_crud.get_by_user_id = AsyncMock(return_value=session)

        with pytest.raises(HTTPException) as exc_info:
            await admin_service.require_active_session(db=mock_db, user=admin_user)

        assert exc_info.value.status_code == 401


# TestGetTransaction
class TestGetTransaction:
    """Tests for admin_service.get_transaction."""

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_transaction")
    async def test_returns_transaction_when_found(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """When the CRUD layer finds the transaction it is returned as-is."""
        tx = MagicMock(spec=Transaction)
        tx.id = uuid.uuid4()
        mock_crud_tx.get = AsyncMock(return_value=tx)

        result = await admin_service.get_transaction(db=mock_db, transaction_id=tx.id)

        assert result is tx

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_transaction")
    async def test_raises_404_when_not_found(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """When the CRUD layer returns None a 404 must be raised."""
        mock_crud_tx.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await admin_service.get_transaction(db=mock_db, transaction_id=uuid.uuid4())

        assert exc_info.value.status_code == 404


# TestListTransactions
class TestListTransactions:
    """Tests for admin_service.list_transactions."""

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_transaction")
    async def test_returns_list_from_crud(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """list_transactions must delegate to crud and return the result unchanged."""
        tx1 = MagicMock(spec=Transaction)
        tx2 = MagicMock(spec=Transaction)
        filters = TransactionListFilters(limit=10, offset=0)
        mock_crud_tx.list_filtered = AsyncMock(return_value=[tx1, tx2])

        result = await admin_service.list_transactions(db=mock_db, filters=filters)

        assert result == [tx1, tx2]
        mock_crud_tx.list_filtered.assert_awaited_once_with(mock_db, filters=filters)

    @pytest.mark.asyncio
    @patch("app.services.admin_service.crud_transaction")
    async def test_returns_empty_list_when_no_matches(
        self,
        mock_crud_tx: MagicMock,
        mock_db: AsyncMock,
    ):
        """list_transactions returns an empty list when no transactions match."""
        filters = TransactionListFilters(limit=10, offset=0)
        mock_crud_tx.list_filtered = AsyncMock(return_value=[])

        result = await admin_service.list_transactions(db=mock_db, filters=filters)

        assert result == []
        mock_crud_tx.list_filtered.assert_awaited_once_with(mock_db, filters=filters)
