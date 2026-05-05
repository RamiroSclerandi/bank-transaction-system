"""Covers registration (user + account created atomically) and the session
lifecycle (login, logout) in isolation by mocking all CRUD dependencies."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.account import Account
from app.models.audit_log import AuditLogAction, UserSession
from app.models.user import User
from app.schemas.user import CustomerUserCreate
from app.services import customer_service


# Helpers
def _mock_request(ip: str = "1.2.3.4") -> MagicMock:
    """Build a minimal mock Request with a configurable client IP."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = ip
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


def _make_account(user_id: uuid.UUID) -> MagicMock:
    """Build a mock Account with zero initial balance."""
    account = MagicMock(spec=Account)
    account.id = uuid.uuid4()
    account.user_id = user_id
    account.balance = 0
    return account


def _make_registration_payload(**overrides: object) -> CustomerUserCreate:
    """Build a valid CustomerUserCreate payload."""
    defaults: dict[str, object] = {
        "name": "John Doe",
        "email": "john@example.com",
        "password": "securepass",
        "national_id": 12345678,
        "phone": 600000001,
        "registered_ip": None,
    }
    defaults.update(overrides)
    return CustomerUserCreate(**defaults)  # type: ignore[arg-type]  # test helper, types are correct


# TestRegister
class TestRegister:
    """Tests for customer_service.register."""

    @pytest.mark.asyncio
    async def test_register_creates_user_account_and_session(
        self,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Successful registration returns user, account, session, and raw token."""
        account = _make_account(customer_user.id)
        session = _make_session(customer_user.id)
        payload = _make_registration_payload()
        request = _mock_request()

        with (
            patch("app.services.customer_service.crud_user") as mock_crud_user,
            patch("app.services.customer_service.crud_account") as mock_crud_account,
            patch(
                "app.services.customer_service.crud_user_session"
            ) as mock_session_crud,
        ):
            mock_crud_user.get_by_email = AsyncMock(return_value=None)
            mock_crud_user.create_customer = AsyncMock(return_value=customer_user)
            mock_crud_account.create = AsyncMock(return_value=account)
            mock_session_crud.upsert = AsyncMock()
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)

            (
                result_user,
                result_account,
                result_session,
                raw_token,
            ) = await customer_service.register(
                db=mock_db, request=request, data=payload
            )

        assert result_user is customer_user
        assert result_account is account
        assert result_session is session
        assert isinstance(raw_token, str) and len(raw_token) > 0
        mock_crud_user.create_customer.assert_awaited_once()
        mock_crud_account.create.assert_awaited_once()
        mock_session_crud.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_duplicate_email_raises_409(
        self,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If the email is already registered, a 409 is raised before any insert."""
        payload = _make_registration_payload()
        request = _mock_request()

        with (
            patch("app.services.customer_service.crud_user") as mock_crud_user,
            patch("app.services.customer_service.crud_account") as mock_crud_account,
        ):
            mock_crud_user.get_by_email = AsyncMock(return_value=customer_user)
            mock_crud_account.create = AsyncMock()

            with pytest.raises(HTTPException) as exc_info:
                await customer_service.register(
                    db=mock_db, request=request, data=payload
                )

        assert exc_info.value.status_code == 409
        mock_crud_account.create.assert_not_awaited()


# TestLogin
class TestLogin:
    """Tests for customer_service.login."""

    @pytest.mark.asyncio
    async def test_no_registered_ip_creates_session_and_logs_login(
        self,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """When registered_ip is None, any IP is accepted and session is created."""
        assert customer_user.registered_ip is None
        request = _mock_request(ip="5.6.7.8")
        session = _make_session(customer_user.id)

        with (
            patch("app.services.customer_service.crud_audit_log") as mock_audit,
            patch(
                "app.services.customer_service.crud_user_session"
            ) as mock_session_crud,
            patch("app.services.customer_service.crud_user") as mock_crud_user,
            patch("app.services.customer_service.verify_password", return_value=True),
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.upsert = AsyncMock()
            mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
            mock_crud_user.get_by_email = AsyncMock(return_value=customer_user)

            result_session, raw_token = await customer_service.login(
                db=mock_db,
                request=request,
                email=customer_user.email,
                password="secret",
            )

        assert result_session is session
        assert isinstance(raw_token, str) and len(raw_token) > 0
        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login
        assert audit_kwargs["user_id"] == customer_user.id
        mock_session_crud.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ip_mismatch_logs_login_failed_and_raises_403(
        self,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """When registered_ip does not match, login_failed is logged and 403 raised."""
        customer_user.registered_ip = "10.0.0.1"
        request = _mock_request(ip="9.9.9.9")

        with (
            patch("app.services.customer_service.crud_audit_log") as mock_audit,
            patch(
                "app.services.customer_service.crud_user_session"
            ) as mock_session_crud,
            patch("app.services.customer_service.crud_user") as mock_crud_user,
            patch("app.services.customer_service.verify_password", return_value=True),
        ):
            mock_audit.create = AsyncMock()
            mock_session_crud.upsert = AsyncMock()
            mock_crud_user.get_by_email = AsyncMock(return_value=customer_user)

            with pytest.raises(HTTPException) as exc_info:
                await customer_service.login(
                    db=mock_db,
                    request=request,
                    email=customer_user.email,
                    password="secret",
                )

        assert exc_info.value.status_code == 403
        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login_failed
        assert audit_kwargs["ip_address"] == "9.9.9.9"
        mock_session_crud.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wrong_password_raises_401(
        self,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Invalid password must raise 401 without creating a session."""
        request = _mock_request()

        with (
            patch(
                "app.services.customer_service.crud_user_session"
            ) as mock_session_crud,
            patch("app.services.customer_service.crud_user") as mock_crud_user,
            patch("app.services.customer_service.verify_password", return_value=False),
        ):
            mock_session_crud.upsert = AsyncMock()
            mock_crud_user.get_by_email = AsyncMock(return_value=customer_user)

            with pytest.raises(HTTPException) as exc_info:
                await customer_service.login(
                    db=mock_db,
                    request=request,
                    email=customer_user.email,
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
            patch(
                "app.services.customer_service.crud_user_session"
            ) as mock_session_crud,
            patch("app.services.customer_service.crud_user") as mock_crud_user,
            patch("app.services.customer_service.verify_password", return_value=False),
        ):
            mock_session_crud.upsert = AsyncMock()
            mock_crud_user.get_by_email = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await customer_service.login(
                    db=mock_db,
                    request=request,
                    email="nobody@example.com",
                    password="secret",
                )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()
