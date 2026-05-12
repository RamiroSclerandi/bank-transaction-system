"""Shared pytest fixtures for unit and integration tests."""

import uuid
from collections.abc import Callable, Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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
        number_hmac="a" * 64,
        number_last4="1111",
        expiration_month=12,
        expiration_year=30,
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
        number_hmac="b" * 64,
        number_last4="0004",
        expiration_month=12,
        expiration_year=30,
    )
    card.account = account
    return card


@pytest.fixture
def mock_db() -> AsyncMock:
    """Return a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
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


# ── Transaction service CRUD patches ──
# Patch settings so PAN_HMAC_KEY is available without a real .env in tests.
_MOCK_PAN_HMAC_KEY = "test-hmac-key"


@pytest.fixture(autouse=True)
def patch_settings_pan_hmac_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure PAN_HMAC_KEY is set for all tests without a real .env in CI."""
    monkeypatch.setattr(
        "app.services.transaction_service.settings",
        MagicMock(PAN_HMAC_KEY=_MOCK_PAN_HMAC_KEY),
    )


@pytest.fixture
def mock_crud_card(debit_card: Card) -> Generator[MagicMock, None, None]:
    """Patch crud_card pre-configured to return debit_card on get_by_hmac."""
    with patch("app.services.transaction_service.crud_card") as mock:
        mock.get_by_hmac = AsyncMock(return_value=debit_card)
        yield mock


@pytest.fixture
def mock_crud_card_credit(credit_card: Card) -> Generator[MagicMock, None, None]:
    """Patch crud_card pre-configured to return credit_card on get_by_hmac."""
    with patch("app.services.transaction_service.crud_card") as mock:
        mock.get_by_hmac = AsyncMock(return_value=credit_card)
        yield mock


@pytest.fixture
def mock_crud_tx() -> Generator[MagicMock, None, None]:
    """Patch crud_transaction; individual tests configure method return values."""
    with patch("app.services.transaction_service.crud_transaction") as mock:
        yield mock


@pytest.fixture
def mock_crud_account(account: Account) -> Generator[MagicMock, None, None]:
    """Patch crud_account pre-configured with get_with_lock and deduct_balance."""
    with patch("app.services.transaction_service.crud_account") as mock:
        mock.get_with_lock = AsyncMock(return_value=account)
        mock.deduct_balance = AsyncMock()
        yield mock


@pytest.fixture
def mock_sqs() -> Generator[AsyncMock, None, None]:
    """Patch sqs_service.publish_international_payment with an AsyncMock."""
    with patch(
        "app.services.transaction_service.sqs_service.publish_international_payment",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


# ── User service CRUD patches ──
@pytest.fixture
def mock_user_crud_user() -> Generator[MagicMock, None, None]:
    """Patch crud_user inside user_service."""
    with patch("app.services.user_service.crud_user") as mock:
        yield mock


@pytest.fixture
def mock_user_crud_account() -> Generator[MagicMock, None, None]:
    """Patch crud_account inside user_service."""
    with patch("app.services.user_service.crud_account") as mock:
        yield mock


# ── Auth service CRUD patches ──
@pytest.fixture
def mock_auth_crud_user() -> Generator[MagicMock, None, None]:
    """Patch crud_user inside auth_service."""
    with patch("app.services.auth_service.crud_user") as mock:
        yield mock


@pytest.fixture
def mock_auth_crud_user_session() -> Generator[MagicMock, None, None]:
    """Patch crud_user_session inside auth_service."""
    with patch("app.services.auth_service.crud_user_session") as mock:
        yield mock


@pytest.fixture
def mock_auth_crud_audit_log() -> Generator[MagicMock, None, None]:
    """Patch crud_audit_log inside auth_service."""
    with patch("app.services.auth_service.crud_audit_log") as mock:
        yield mock


@pytest.fixture
def mock_auth_crud_session_history() -> Generator[MagicMock, None, None]:
    """Patch crud_session_history inside auth_service."""
    with patch("app.services.auth_service.crud_session_history") as mock:
        yield mock


@pytest.fixture
def mock_auth_verify_password() -> Generator[MagicMock, None, None]:
    """Patch verify_password inside auth_service; defaults to returning True."""
    with patch("app.services.auth_service.verify_password", return_value=True) as mock:
        yield mock


# ── Daily Jobs service / internal endpoints patches ──


@pytest.fixture
def mock_subprocess_run() -> Generator[AsyncMock, None, None]:
    """Fixture to mock asyncio.create_subprocess_exec."""
    with patch(
        "app.services.backup_service.asyncio.create_subprocess_exec",
        new_callable=AsyncMock,
    ) as mock:
        process_mock = AsyncMock()
        process_mock.returncode = 0
        process_mock.communicate = AsyncMock()
        mock.return_value = process_mock
        yield mock


@pytest.fixture
def mock_os_makedirs() -> Generator[MagicMock, None, None]:
    """Fixture to mock os.makedirs."""
    with patch("app.services.backup_service.os.makedirs") as mock:
        yield mock


@pytest.fixture
def mock_boto3_client() -> Generator[MagicMock, None, None]:
    """Fixture to mock boto3.client."""
    with patch("app.services.backup_service.boto3.client") as mock:
        mock_client = MagicMock()
        mock.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_archive_service() -> Generator[AsyncMock, None, None]:
    """Fixture to mock archive_service.copy_transactions_to_history."""
    with patch(
        "app.api.api_v1.endpoints.internal.archive_service.copy_transactions_to_history",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


@pytest.fixture
def mock_backup_service() -> Generator[AsyncMock, None, None]:
    """Fixture to mock backup_service.execute_daily_backup."""
    with patch(
        "app.api.api_v1.endpoints.internal.backup_service.execute_daily_backup",
        new_callable=AsyncMock,
    ) as mock:
        yield mock
