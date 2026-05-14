"""
Integration tests for transaction atomicity.

Concurrent debit on the same account: exactly one succeeds, one fails with 402.
Uses committed_async_client for real DB visibility across concurrent requests.

Runs against a real Postgres container.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from app.crud.account import crud_account
from app.models.transaction import Transaction, TransactionStatus
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration


async def _seed_customer(
    client: AsyncClient,
    suffix: str = "",
) -> tuple[str, str]:
    """Register a new customer via the API and return (email, password)."""
    email = f"atomic_{uuid.uuid4().hex[:8]}_{suffix}@test.com"
    password = "testpass123"  # noqa: S105
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": f"Atomic User {suffix}",
            "email": email,
            "password": password,
            "national_id": int(uuid.uuid4().int % 99_999_998) + 1,
            "phone": int(uuid.uuid4().int % 999_999_998) + 1,
        },
    )
    assert resp.status_code == 201, f"Seed failed: {resp.text}"
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> str:
    """Login and return session_token."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["session_token"]


class TestTransactionAtomicity:
    """Concurrent debit: one win, one fail — balance must reach exactly 0."""

    @pytest.mark.asyncio
    async def test_concurrent_debit_one_wins_one_fails(
        self,
        committed_async_client: AsyncClient,
        async_session_factory: async_sessionmaker,
    ) -> None:
        """
        Two concurrent debit requests for the full balance:
        - Exactly one must return 201 (completed)
        - Exactly one must return 402 (insufficient funds)
        - Final balance must be 0
        """
        # ── Seed user + add exact balance ──
        email, password = await _seed_customer(committed_async_client, "atomicity")
        token = await _login(committed_async_client, email, password)
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Add exactly 100.0000 — enough for one debit of 100
        add_resp = await committed_async_client.post(
            "/api/v1/accounts/add-balance",
            json={"amount": "100.0000"},
            headers=auth_headers,
        )
        assert add_resp.status_code == 200, add_resp.text

        card_payload = {
            "card": {
                "number": "5500-0000-0000-0004",
                "card_type": "debit",
                "expiration_month": 12,
                "expiration_year": 30,
                "cvv": "123",
            },
            "destination_account": "dest-account-atomicity-test",
            "amount": "100.0000",
            "type": "national",
        }

        # Fire two concurrent debit requests
        results = await asyncio.gather(
            committed_async_client.post(
                "/api/v1/transactions",
                json=card_payload,
                headers=auth_headers,
            ),
            committed_async_client.post(
                "/api/v1/transactions",
                json=card_payload,
                headers=auth_headers,
            ),
            return_exceptions=True,
        )

        statuses = [r.status_code for r in results if hasattr(r, "status_code")]
        assert sorted(statuses) == [201, 402], (
            f"Expected exactly one 201 and one 402, got: {statuses}. "
            f"Bodies: {[r.text for r in results if hasattr(r, 'text')]}"
        )

        # Final balance must be 0 — look up via session factory
        # Get user_id from account in the response
        account_data = add_resp.json()
        account_id = uuid.UUID(account_data["id"])
        async with async_session_factory() as session:
            final_account = await crud_account.get(session, account_id=account_id)
            assert final_account is not None
            assert final_account.balance == Decimal(
                "0.0000"
            ), f"Expected balance 0.0000 but got {final_account.balance}"

            # Exactly one transaction must have been committed as completed
            tx_count_result = await session.execute(
                select(func.count()).where(
                    Transaction.status == TransactionStatus.completed
                )
            )
            completed_count = tx_count_result.scalar_one()
            assert (
                completed_count == 1
            ), f"Expected exactly 1 completed transaction, got {completed_count}"
