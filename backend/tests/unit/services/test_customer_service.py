"""
Covers registration (user + account created atomically) and the session
lifecycle (login, logout) in isolation by mocking all CRUD dependencies.
"""

import uuid
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.account import Account
from app.models.audit_log import AuditLogAction
from app.models.user import User
from app.schemas.user import CustomerUserCreate
from app.services import customer_service
from fastapi import HTTPException


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
    @patch("app.services.customer_service.crud_user_session")
    @patch("app.services.customer_service.crud_account")
    @patch("app.services.customer_service.crud_user")
    async def test_register_creates_user_account_and_session(
        self,
        mock_crud_user: MagicMock,
        mock_crud_account: MagicMock,
        mock_session_crud: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """Successful registration returns user, account, session, and raw token."""
        account = _make_account(customer_user.id)
        session = make_session(customer_user.id)
        payload = _make_registration_payload()
        request = mock_request()
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
        ) = await customer_service.register(db=mock_db, request=request, data=payload)

        assert result_user is customer_user
        assert result_account is account
        assert result_session is session
        assert isinstance(raw_token, str) and len(raw_token) > 0
        mock_crud_user.create_customer.assert_awaited_once()
        mock_crud_account.create.assert_awaited_once()
        mock_session_crud.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.services.customer_service.crud_account")
    @patch("app.services.customer_service.crud_user")
    async def test_register_duplicate_email_raises_409(
        self,
        mock_crud_user: MagicMock,
        mock_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """If the email is already registered, a 409 is raised before any insert."""
        payload = _make_registration_payload()
        request = mock_request()
        mock_crud_user.get_by_email = AsyncMock(return_value=customer_user)
        mock_crud_account.create = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await customer_service.register(db=mock_db, request=request, data=payload)

        assert exc_info.value.status_code == 409
        mock_crud_account.create.assert_not_awaited()


# TestLogin
class TestLogin:
    """Tests for customer_service.login."""

    @pytest.mark.asyncio
    @patch("app.services.customer_service.verify_password", return_value=True)
    @patch("app.services.customer_service.crud_user")
    @patch("app.services.customer_service.crud_user_session")
    @patch("app.services.customer_service.crud_audit_log")
    async def test_no_registered_ip_creates_session_and_logs_login(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """When registered_ip is None, any IP is accepted and session is created."""
        assert customer_user.registered_ip is None
        request = mock_request(ip="5.6.7.8")
        session = make_session(customer_user.id)
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
    @patch("app.services.customer_service.verify_password", return_value=True)
    @patch("app.services.customer_service.crud_user")
    @patch("app.services.customer_service.crud_user_session")
    @patch("app.services.customer_service.crud_audit_log")
    async def test_ip_mismatch_logs_login_failed_and_raises_403(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """When registered_ip does not match, login_failed is logged and 403 raised."""
        customer_user.registered_ip = "10.0.0.1"
        request = mock_request(ip="9.9.9.9")
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
    @patch("app.services.customer_service.verify_password", return_value=False)
    @patch("app.services.customer_service.crud_user")
    @patch("app.services.customer_service.crud_user_session")
    async def test_wrong_password_raises_401(
        self,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Invalid password must raise 401 without creating a session."""
        request = mock_request()
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
    @patch("app.services.customer_service.verify_password", return_value=False)
    @patch("app.services.customer_service.crud_user")
    @patch("app.services.customer_service.crud_user_session")
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
            await customer_service.login(
                db=mock_db,
                request=request,
                email="nobody@example.com",
                password="secret",
            )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()
