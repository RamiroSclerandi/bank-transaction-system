"""
Tests for auth_service: login and logout for both admin and customer roles.
Covers credential validation, IP policy, audit logging, and session management.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.audit_log import AuditLogAction
from app.models.user import User, UserRole
from app.services import auth_service
from fastapi import HTTPException

# ── Helpers ───

_ROLES = [
    pytest.param(UserRole.admin, id="admin"),
    pytest.param(UserRole.customer, id="customer"),
]


def _patch_target(name: str) -> str:
    return f"app.services.auth_service.{name}"


# ── TestLogin ───


class TestLogin:
    """Tests for auth_service.login (parameterised by role)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("verify_password"), return_value=True)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    @patch(_patch_target("crud_audit_log"))
    async def test_no_registered_ip_creates_session_and_logs_login(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        role: UserRole,
        admin_user: User,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """When registered_ip is None, any IP is accepted and session is created."""
        user = admin_user if role == UserRole.admin else customer_user
        user.role = role
        assert user.registered_ip is None
        request = mock_request(ip="5.6.7.8")
        session = make_session(user.id)
        mock_audit.create = AsyncMock()
        mock_session_crud.upsert = AsyncMock()
        mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
        mock_crud_user.get_by_email = AsyncMock(return_value=user)

        result_session, raw_token = await auth_service.login(
            db=mock_db, request=request, email=user.email, password="secret", role=role
        )

        assert result_session is session
        assert isinstance(raw_token, str) and len(raw_token) > 0
        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login
        assert audit_kwargs["user_id"] == user.id
        mock_session_crud.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("verify_password"), return_value=True)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    @patch(_patch_target("crud_audit_log"))
    async def test_matching_registered_ip_creates_session(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        role: UserRole,
        admin_user: User,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """When registered_ip matches the request IP the session is created normally."""
        user = admin_user if role == UserRole.admin else customer_user
        user.role = role
        user.registered_ip = "10.0.0.1"
        request = mock_request(ip="10.0.0.1")
        session = make_session(user.id)
        mock_audit.create = AsyncMock()
        mock_session_crud.upsert = AsyncMock()
        mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
        mock_crud_user.get_by_email = AsyncMock(return_value=user)

        result_session, _ = await auth_service.login(
            db=mock_db, request=request, email=user.email, password="secret", role=role
        )

        assert result_session is session
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("verify_password"), return_value=True)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    @patch(_patch_target("crud_audit_log"))
    async def test_ip_mismatch_logs_login_failed_and_raises_403(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        role: UserRole,
        admin_user: User,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """When registered_ip does not match the request IP, 403 raised."""
        user = admin_user if role == UserRole.admin else customer_user
        user.role = role
        user.registered_ip = "10.0.0.1"
        request = mock_request(ip="9.9.9.9")
        mock_audit.create = AsyncMock()
        mock_session_crud.upsert = AsyncMock()
        mock_crud_user.get_by_email = AsyncMock(return_value=user)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.login(
                db=mock_db,
                request=request,
                email=user.email,
                password="secret",
                role=role,
            )

        assert exc_info.value.status_code == 403
        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.login_failed
        assert audit_kwargs["ip_address"] == "9.9.9.9"
        mock_session_crud.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("verify_password"), return_value=True)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    @patch(_patch_target("crud_audit_log"))
    async def test_login_ip_is_recorded_on_audit_entry(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        role: UserRole,
        admin_user: User,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
        make_session: Callable[..., MagicMock],
    ):
        """The client IP extracted from the request is stored in the audit log."""
        user = admin_user if role == UserRole.admin else customer_user
        user.role = role
        expected_ip = "203.0.113.42"
        request = mock_request(ip=expected_ip)
        session = make_session(user.id)
        mock_audit.create = AsyncMock()
        mock_session_crud.upsert = AsyncMock()
        mock_session_crud.get_by_user_id = AsyncMock(return_value=session)
        mock_crud_user.get_by_email = AsyncMock(return_value=user)

        await auth_service.login(
            db=mock_db, request=request, email=user.email, password="secret", role=role
        )

        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["ip_address"] == expected_ip

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("verify_password"), return_value=False)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    async def test_wrong_password_raises_401(
        self,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        role: UserRole,
        admin_user: User,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Invalid password must raise 401 without creating a session."""
        user = admin_user if role == UserRole.admin else customer_user
        user.role = role
        request = mock_request()
        mock_session_crud.upsert = AsyncMock()
        mock_crud_user.get_by_email = AsyncMock(return_value=user)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.login(
                db=mock_db,
                request=request,
                email=user.email,
                password="wrong",
                role=role,
            )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("verify_password"), return_value=False)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    async def test_unknown_email_raises_401(
        self,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        role: UserRole,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Unknown email must raise 401 without leaking whether the email exists."""
        request = mock_request()
        mock_session_crud.upsert = AsyncMock()
        mock_crud_user.get_by_email = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.login(
                db=mock_db,
                request=request,
                email="nobody@example.com",
                password="secret",
                role=role,
            )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(_patch_target("verify_password"), return_value=True)
    @patch(_patch_target("crud_user"))
    @patch(_patch_target("crud_user_session"))
    async def test_wrong_role_raises_401(
        self,
        mock_session_crud: MagicMock,
        mock_crud_user: MagicMock,
        mock_verify: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Correct password but wrong role must raise 401."""
        admin_user.role = UserRole.admin
        request = mock_request()
        mock_session_crud.upsert = AsyncMock()
        mock_crud_user.get_by_email = AsyncMock(return_value=admin_user)

        with pytest.raises(HTTPException) as exc_info:
            await auth_service.login(
                db=mock_db,
                request=request,
                email=admin_user.email,
                password="secret",
                role=UserRole.customer,  # wrong role
            )

        assert exc_info.value.status_code == 401
        mock_session_crud.upsert.assert_not_awaited()


# ── TestLogout ──


class TestLogout:
    """Tests for auth_service.logout."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", _ROLES)
    @patch(_patch_target("crud_user_session"))
    @patch(_patch_target("crud_audit_log"))
    async def test_logout_writes_audit_and_deletes_session(
        self,
        mock_audit: MagicMock,
        mock_session_crud: MagicMock,
        role: UserRole,
        admin_user: User,
        customer_user: User,
        mock_db: AsyncMock,
        mock_request: Callable[..., MagicMock],
    ):
        """Logout must record an audit logout event and delete the session row."""
        user = admin_user if role == UserRole.admin else customer_user
        user.role = role
        request = mock_request()
        mock_audit.create = AsyncMock()
        mock_session_crud.delete = AsyncMock()

        await auth_service.logout(db=mock_db, request=request, user=user)

        mock_audit.create.assert_awaited_once()
        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["action"] == AuditLogAction.logout
        assert audit_kwargs["user_id"] == user.id
        mock_session_crud.delete.assert_awaited_once()
        delete_kwargs = mock_session_crud.delete.call_args.kwargs
        assert delete_kwargs["user_id"] == user.id

    @pytest.mark.asyncio
    @patch(_patch_target("crud_user_session"))
    @patch(_patch_target("crud_audit_log"))
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

        await auth_service.logout(db=mock_db, request=request, user=admin_user)

        audit_kwargs = mock_audit.create.call_args.kwargs
        assert audit_kwargs["ip_address"] == "192.168.1.50"
