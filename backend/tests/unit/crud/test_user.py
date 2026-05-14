"""
Unit tests for CRUDUser.

Uses AsyncMock sessions — no real DB.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.user import CRUDUser
from app.models.user import User, UserRole
from app.schemas.user import AdminUserCreate, CustomerUserCreate


@pytest.fixture
def crud() -> CRUDUser:
    """Return a fresh CRUDUser instance."""
    return CRUDUser()


def _db_returning(value: object) -> AsyncMock:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = value
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ── get ───────────────────────────────────────────────────────────────────────


class TestGet:
    """Tests for CRUDUser.get."""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(
        self, crud: CRUDUser, customer_user: User
    ) -> None:
        """get() returns the user when found."""
        db = _db_returning(customer_user)
        result = await crud.get(db, user_id=customer_user.id)
        assert result is customer_user

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, crud: CRUDUser) -> None:
        """get() returns None when the user is not found."""
        db = _db_returning(None)
        result = await crud.get(db, user_id=uuid.uuid4())
        assert result is None


# ── get_by_email ──────────────────────────────────────────────────────────────


class TestGetByEmail:
    """Tests for CRUDUser.get_by_email."""

    @pytest.mark.asyncio
    async def test_returns_user_for_known_email(
        self, crud: CRUDUser, customer_user: User
    ) -> None:
        """get_by_email() returns the user when the email is found."""
        db = _db_returning(customer_user)
        result = await crud.get_by_email(db, email=customer_user.email)
        assert result is customer_user

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_email(self, crud: CRUDUser) -> None:
        """get_by_email() returns None when the email is not found."""
        db = _db_returning(None)
        result = await crud.get_by_email(db, email="nobody@example.com")
        assert result is None


# ── get_by_national_id ────────────────────────────────────────────────────────


class TestGetByNationalId:
    """Tests for CRUDUser.get_by_national_id."""

    @pytest.mark.asyncio
    async def test_returns_user(self, crud: CRUDUser, customer_user: User) -> None:
        """get_by_national_id() returns the user when the national ID is found."""
        db = _db_returning(customer_user)
        result = await crud.get_by_national_id(
            db, national_id=customer_user.national_id
        )
        assert result is customer_user

    @pytest.mark.asyncio
    async def test_returns_none(self, crud: CRUDUser) -> None:
        """get_by_national_id() returns None when the national ID is not found."""
        db = _db_returning(None)
        result = await crud.get_by_national_id(db, national_id=99999999)
        assert result is None


# ── get_by_phone ──────────────────────────────────────────────────────────────


class TestGetByPhone:
    """Tests for CRUDUser.get_by_phone."""

    @pytest.mark.asyncio
    async def test_returns_user(self, crud: CRUDUser, customer_user: User) -> None:
        """get_by_phone() returns the user when the phone number is found."""
        db = _db_returning(customer_user)
        result = await crud.get_by_phone(db, phone=customer_user.phone)
        assert result is customer_user

    @pytest.mark.asyncio
    async def test_returns_none(self, crud: CRUDUser) -> None:
        """get_by_phone() returns None when the phone number is not found."""
        db = _db_returning(None)
        result = await crud.get_by_phone(db, phone=999999999)
        assert result is None


# ── is_admin ──────────────────────────────────────────────────────────────────


class TestIsAdmin:
    """Tests for CRUDUser.is_admin."""

    @pytest.mark.asyncio
    async def test_admin_user_returns_true(
        self, crud: CRUDUser, admin_user: User
    ) -> None:
        """is_admin() returns True for admin users."""
        result = await crud.is_admin(admin_user)
        assert result is True

    @pytest.mark.asyncio
    async def test_customer_user_returns_false(
        self, crud: CRUDUser, customer_user: User
    ) -> None:
        """is_admin() returns False for customer users."""
        result = await crud.is_admin(customer_user)
        assert result is False


# ── create_customer ───────────────────────────────────────────────────────────


class TestCreateCustomer:
    """Tests for CRUDUser.create_customer."""

    @pytest.mark.asyncio
    async def test_creates_customer_with_hashed_password(
        self, crud: CRUDUser, mock_crud_user_hash_password: MagicMock
    ) -> None:
        """create_customer() adds a user with role=customer and hashed password."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        data = CustomerUserCreate(
            name="Alice",
            email="alice@example.com",
            password="securepass",  # noqa: S106
            national_id=11111111,
            phone=600000001,
        )

        result = await crud.create_customer(db, data=data)

        assert result.role == UserRole.customer
        assert result.email == "alice@example.com"
        assert result.password_hash == "hashed"  # noqa: S105
        db.add.assert_called_once()
        db.flush.assert_awaited_once()


# ── create_admin ──────────────────────────────────────────────────────────────


class TestCreateAdmin:
    """Tests for CRUDUser.create_admin."""

    @pytest.mark.asyncio
    async def test_creates_admin_with_role_admin(
        self, crud: CRUDUser, mock_crud_user_hash_password: MagicMock
    ) -> None:
        """create_admin() adds a user with role=admin."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        data = AdminUserCreate(
            name="Bob Admin",
            email="bob@example.com",
            password="adminpass",  # noqa: S106
            national_id=22222222,
            phone=611111111,
        )

        result = await crud.create_admin(db, data=data)

        assert result.role == UserRole.admin
        assert result.email == "bob@example.com"
