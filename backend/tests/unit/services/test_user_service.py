"""Tests for user_service: customer registration and admin user creation."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.account import Account
from app.models.user import User
from app.schemas.user import AdminUserCreate, CustomerUserCreate
from app.services import user_service
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


def _make_integrity_error(constraint_name: str) -> IntegrityError:
    orig = MagicMock()
    orig.constraint_name = constraint_name
    return IntegrityError(statement=None, params=None, orig=orig)


# ── Helpers ───
def _make_account(user_id: uuid.UUID) -> MagicMock:
    account = MagicMock(spec=Account)
    account.id = uuid.uuid4()
    account.user_id = user_id
    account.balance = 0
    return account


def _make_customer_payload(**overrides: object) -> CustomerUserCreate:
    defaults: dict[str, object] = {
        "name": "John Doe",
        "email": "john@example.com",
        "password": "securepass",
        "national_id": 12345678,
        "phone": 600000001,
        "registered_ip": None,
    }
    defaults.update(overrides)
    return CustomerUserCreate(**defaults)  # type: ignore[arg-type]


def _make_admin_payload(**overrides: object) -> AdminUserCreate:
    defaults: dict[str, object] = {
        "name": "Admin User",
        "email": "admin2@example.com",
        "password": "adminpass",
        "national_id": 99999999,
        "phone": 699999999,
        "registered_ip": None,
    }
    defaults.update(overrides)
    return AdminUserCreate(**defaults)  # type: ignore[arg-type]


# ── TestRegisterCustomer ──
class TestRegisterCustomer:
    """Tests for user_service.register_customer."""

    @pytest.mark.asyncio
    async def test_creates_user_and_account(
        self,
        mock_user_crud_user: MagicMock,
        mock_user_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Successful registration returns user and account (no session)."""
        account = _make_account(customer_user.id)
        payload = _make_customer_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=None)
        mock_user_crud_user.create_customer = AsyncMock(return_value=customer_user)
        mock_user_crud_account.create = AsyncMock(return_value=account)

        result_user, result_account = await user_service.register_customer(
            db=mock_db, data=payload
        )

        assert result_user is customer_user
        assert result_account is account
        mock_user_crud_user.create_customer.assert_awaited_once()
        mock_user_crud_account.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        mock_user_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If the email is already registered, a 409 is raised before any insert."""
        payload = _make_customer_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=customer_user)
        mock_user_crud_account.create = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.register_customer(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        mock_user_crud_account.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_national_id_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        mock_user_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If national_id is already registered, a 409 is raised before any insert."""
        payload = _make_customer_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=customer_user)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=None)
        mock_user_crud_user.create_customer = AsyncMock()
        mock_user_crud_account.create = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.register_customer(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        assert "national_id" in exc_info.value.detail
        mock_user_crud_user.create_customer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_phone_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        mock_user_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If phone is already registered, a 409 is raised before any insert."""
        payload = _make_customer_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=customer_user)
        mock_user_crud_user.create_customer = AsyncMock()
        mock_user_crud_account.create = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.register_customer(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        assert "phone" in exc_info.value.detail
        mock_user_crud_user.create_customer.assert_not_awaited()


# ── TestCreateAdmin ──
class TestCreateAdmin:
    """Tests for user_service.create_admin."""

    @pytest.mark.asyncio
    async def test_creates_admin_user(
        self,
        mock_user_crud_user: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """Successful call creates and returns the admin user."""
        payload = _make_admin_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=None)
        mock_user_crud_user.create_admin = AsyncMock(return_value=admin_user)

        result = await user_service.create_admin(db=mock_db, data=payload)

        assert result is admin_user
        mock_user_crud_user.create_admin.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If the email is already registered, a 409 is raised."""
        payload = _make_admin_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=admin_user)
        mock_user_crud_user.create_admin = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.create_admin(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        mock_user_crud_user.create_admin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_national_id_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If national_id is already registered, a 409 is raised before any insert."""
        payload = _make_admin_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=admin_user)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=None)
        mock_user_crud_user.create_admin = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.create_admin(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        assert "national_id" in exc_info.value.detail
        mock_user_crud_user.create_admin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_phone_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        admin_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """If phone is already registered, a 409 is raised before any insert."""
        payload = _make_admin_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=admin_user)
        mock_user_crud_user.create_admin = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.create_admin(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        assert "phone" in exc_info.value.detail
        mock_user_crud_user.create_admin.assert_not_awaited()


# ── TestIntegrityErrorSafetyNet ──
class TestIntegrityErrorSafetyNet:
    """Safety-net tests for _raise_for_integrity_error in user_service."""

    @pytest.mark.asyncio
    async def test_integrity_error_known_constraint_raises_409(
        self,
        mock_user_crud_user: MagicMock,
        mock_user_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """IntegrityError on a known constraint is converted to HTTPException 409."""
        payload = _make_customer_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=None)
        mock_user_crud_user.create_customer = AsyncMock(
            side_effect=_make_integrity_error("users_national_id_key")
        )
        mock_user_crud_account.create = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await user_service.register_customer(db=mock_db, data=payload)

        assert exc_info.value.status_code == 409
        assert "national_id" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_integrity_error_unknown_constraint_reraises(
        self,
        mock_user_crud_user: MagicMock,
        mock_user_crud_account: MagicMock,
        customer_user: User,
        mock_db: AsyncMock,
    ) -> None:
        """IntegrityError on an unknown constraint is re-raised as-is."""
        payload = _make_customer_payload()
        mock_user_crud_user.get_by_email = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_national_id = AsyncMock(return_value=None)
        mock_user_crud_user.get_by_phone = AsyncMock(return_value=None)
        mock_user_crud_user.create_customer = AsyncMock(
            side_effect=_make_integrity_error("some_other_constraint")
        )
        mock_user_crud_account.create = AsyncMock()

        with pytest.raises(IntegrityError):
            await user_service.register_customer(db=mock_db, data=payload)
