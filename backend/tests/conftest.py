"""Shared pytest fixtures for unit and integration tests."""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.account import Account
from app.models.card import Card, CardType
from app.models.user import User, UserRole


@pytest.fixture
def customer_user() -> User:
    """Return a minimal customer User fixture."""
    user = User(
        id=uuid.uuid4(),
        name="Test Customer",
        national_id=12345678,
        email="customer@example.com",
        phone=600000000,
        password_hash="$2b$12$test_placeholder",
        role=UserRole.customer,
        registered_ip=None,
    )
    return user


@pytest.fixture
def admin_user() -> User:
    """Return a minimal admin User fixture."""
    user = User(
        id=uuid.uuid4(),
        name="Test Admin",
        national_id=87654321,
        email="admin@example.com",
        phone=611111111,
        password_hash="$2b$12$test_placeholder",
        role=UserRole.admin,
        registered_ip=None,
    )
    return user


@pytest.fixture
def account(customer_user: User) -> Account:
    """Return an Account fixture linked to the customer user."""
    acc = Account(
        id=uuid.uuid4(),
        user_id=customer_user.id,
        balance=Decimal("1000.0000"),
    )
    acc.user = customer_user
    return acc


@pytest.fixture
def debit_card(account: Account) -> Card:
    """Return a debit Card fixture linked to the account."""
    card = Card(
        id=uuid.uuid4(),
        account_id=account.id,
        card_type=CardType.debit,
    )
    card.account = account
    return card


@pytest.fixture
def credit_card(account: Account) -> Card:
    """Return a credit Card fixture linked to the account."""
    card = Card(
        id=uuid.uuid4(),
        account_id=account.id,
        card_type=CardType.credit,
    )
    card.account = account
    return card


@pytest.fixture
def mock_db() -> AsyncMock:
    """Return a mock AsyncSession."""
    db = AsyncMock()
    db.begin = MagicMock()
    db.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    db.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return db
