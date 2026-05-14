"""
Integration tests for scheduled transaction processing.

Create a scheduled transaction → patch to past → trigger cron → verify completed.

Runs against a real Postgres container.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import settings
from app.crud.transaction import crud_transaction
from app.models.transaction import Transaction, TransactionStatus
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> str:
    """Register a customer and return a session token."""
    email = f"sched_{uuid.uuid4().hex[:8]}@test.com"
    password = "testpass123"  # noqa: S105
    reg_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Scheduled User",
            "email": email,
            "password": password,
            "national_id": int(uuid.uuid4().int % 99_999_998) + 1,
            "phone": int(uuid.uuid4().int % 999_999_998) + 1,
        },
    )
    assert reg_resp.status_code == 201, f"Register failed: {reg_resp.text}"

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    return login_resp.json()["session_token"]


class TestScheduledTransactionFlow:
    """Create scheduled transaction → cron processes it → status = completed."""

    @pytest.mark.asyncio
    async def test_scheduled_transaction_processed_by_cron(
        self,
        committed_async_client: AsyncClient,
        async_session_factory: async_sessionmaker,
    ) -> None:
        """
        Full flow:
          1. Register user + login
          2. Add balance via API
          3. Create a transaction with scheduled_for = far future (validator accepts it)
          4. Directly update scheduled_for to the past so cron picks it up
          5. Call POST /api/v1/internal/cron/process-scheduled → processed >= 1
          6. Verify transaction status is completed
        """
        # ── Seed ──
        token = await _register_and_login(committed_async_client)
        auth_headers = {"Authorization": f"Bearer {token}"}

        # Add balance
        add_resp = await committed_async_client.post(
            "/api/v1/accounts/add-balance",
            json={"amount": "500.0000"},
            headers=auth_headers,
        )
        assert add_resp.status_code == 200, add_resp.text

        # Create scheduled transaction (far future so validator accepts it)
        far_future = (datetime.now(UTC) + timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        tx_resp = await committed_async_client.post(
            "/api/v1/transactions",
            json={
                "card": {
                    "number": "4111-1111-2222-3344",
                    "card_type": "debit",
                    "expiration_month": 12,
                    "expiration_year": 30,
                    "cvv": "321",
                },
                "destination_account": "dest-scheduled-cron-test",
                "amount": "50.0000",
                "type": "national",
                "scheduled_for": far_future,
            },
            headers=auth_headers,
        )
        assert tx_resp.status_code == 201, tx_resp.text
        tx_id = uuid.UUID(tx_resp.json()["id"])
        assert tx_resp.json()["status"] == "scheduled"

        # Patch scheduled_for to past so cron picks it up
        past_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(Transaction)
                    .where(Transaction.id == tx_id)
                    .values(scheduled_for=past_time)
                )

        # Trigger cron
        cron_resp = await committed_async_client.post(
            "/api/v1/internal/cron/process-scheduled",
            headers={"X-Internal-Api-Key": settings.INTERNAL_SERVICE_API_KEY},
        )
        assert cron_resp.status_code == 200, cron_resp.text
        cron_data = cron_resp.json()
        assert cron_data["processed"] >= 1, f"Expected processed>=1, got: {cron_data}"

        # Verify final status
        async with async_session_factory() as session:
            final_tx = await crud_transaction.get(session, transaction_id=tx_id)
            assert final_tx is not None
            assert (
                final_tx.status == TransactionStatus.completed
            ), f"Expected completed but got {final_tx.status}"
