"""Shared pytest fixtures for unit and integration tests."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.account import Account
from app.models.audit_log import UserSession
from app.models.card import Card, CardType
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
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


@pytest.fixture
def mock_request() -> Callable[..., MagicMock]:
    """
    Factory fixture: returns a callable that builds a mock Request.
    Usage: request = mock_request(ip="1.2.3.4")
    """

    def _make(ip: str = "1.2.3.4") -> MagicMock:
        request = MagicMock()
        request.client = MagicMock()
        request.client.host = ip
        request.headers.get = MagicMock(return_value="Bearer test-token")
        return request

    return _make


@pytest.fixture
def make_session() -> Callable[..., MagicMock]:
    """
    Factory fixture: returns a callable that builds a mock UserSession.
    Usage: session = make_session(user_id=some_uuid)
    """

    def _make(
        user_id: uuid.UUID,
        expires_at: datetime | None = None,
    ) -> MagicMock:
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

    return _make


@pytest.fixture
def make_transaction() -> Callable[..., MagicMock]:
    """
    Factory fixture: returns a callable that builds a minimal Transaction mock.
    Usage: tx = make_transaction(TransactionStatus.completed)
    """

    def _make(
        status: TransactionStatus,
        method: TransactionMethod = TransactionMethod.debit,
        tx_type: TransactionType = TransactionType.national,
    ) -> MagicMock:
        tx = MagicMock(spec=Transaction)
        tx.id = uuid.uuid4()
        tx.status = status
        tx.method = method
        tx.type = tx_type
        tx.origin_account = uuid.uuid4()
        tx.source_card = uuid.uuid4()
        tx.destination_account = "dest-account-123"
        tx.amount = Decimal("100.00")
        tx.account = MagicMock()
        tx.account.user_id = uuid.uuid4()
        return tx

    return _make
