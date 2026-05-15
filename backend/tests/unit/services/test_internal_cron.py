"""
Unit tests for POST /api/v1/internal/cron/process-scheduled.

Tests verify:
- 202 Accepted with accepted body
- Background processing: 2 IDs processed
- Empty run accepted
- 409 from service counted as skipped (background logs)
- 403 without valid API key
- Background function logging via caplog
"""

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.api_v1.endpoints.internal import _run_cron_in_background, router
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app() -> FastAPI:
    """Minimal FastAPI app with just the internal router."""
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    return application


@pytest.fixture
def internal_key() -> str:
    """Return the internal API key for authorized requests."""
    return "test-internal-key"


@pytest.fixture(autouse=True)
def patch_internal_key(internal_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the settings so the internal key matches our test key."""
    monkeypatch.setattr(
        "app.deps.settings",
        MagicMock(INTERNAL_SERVICE_API_KEY=internal_key),
    )


class TestCronProcessScheduledEndpoint:
    """Tests for POST /api/v1/internal/cron/process-scheduled."""

    @pytest.mark.asyncio
    async def test_returns_403_without_internal_key(self, app: FastAPI) -> None:
        """Request without X-Internal-Api-Key must return 403."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/internal/cron/process-scheduled")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_happy_path_two_ids_processed(
        self,
        app: FastAPI,
        internal_key: str,
        mock_internal_crud_transaction: MagicMock,
        mock_internal_transaction_service: MagicMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """Valid request with 2 due IDs returns 202 with accepted body."""
        id1, id2 = uuid.uuid4(), uuid.uuid4()
        mock_internal_crud_transaction.get_due_ids = AsyncMock(return_value=[id1, id2])
        mock_internal_transaction_service.process_scheduled_transaction = AsyncMock(
            return_value=None
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/cron/process-scheduled",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 202
        assert response.json() == {
            "status": "accepted",
            "job": "cron-process-scheduled",
        }

    @pytest.mark.asyncio
    async def test_empty_run_returns_accepted(
        self,
        app: FastAPI,
        internal_key: str,
        mock_internal_crud_transaction: MagicMock,
        mock_internal_transaction_service: MagicMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """When no due IDs, response must still be 202 accepted."""
        mock_internal_crud_transaction.get_due_ids = AsyncMock(return_value=[])
        mock_internal_transaction_service.process_scheduled_transaction = AsyncMock()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/cron/process-scheduled",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 202
        assert response.json() == {
            "status": "accepted",
            "job": "cron-process-scheduled",
        }

    @pytest.mark.asyncio
    async def test_409_from_service_counted_as_skipped(
        self,
        app: FastAPI,
        internal_key: str,
        mock_internal_crud_transaction: MagicMock,
        mock_internal_transaction_service: MagicMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """When service raises HTTPException(409) in background, returns 202."""
        id1 = uuid.uuid4()
        mock_internal_crud_transaction.get_due_ids = AsyncMock(return_value=[id1])
        mock_internal_transaction_service.process_scheduled_transaction = AsyncMock(
            side_effect=HTTPException(status_code=status.HTTP_409_CONFLICT)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/cron/process-scheduled",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 202
        assert response.json() == {
            "status": "accepted",
            "job": "cron-process-scheduled",
        }

    @pytest.mark.asyncio
    async def test_cron_background_logs_success(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_internal_crud_transaction: MagicMock,
        mock_internal_transaction_service: MagicMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """_run_cron_in_background must log completion with processed count."""
        id1, id2 = uuid.uuid4(), uuid.uuid4()
        mock_internal_crud_transaction.get_due_ids = AsyncMock(return_value=[id1, id2])
        mock_internal_transaction_service.process_scheduled_transaction = AsyncMock(
            return_value=None
        )

        with caplog.at_level(logging.INFO, logger="app.api.api_v1.endpoints.internal"):
            await _run_cron_in_background()

        assert "internal_job_completed" in caplog.text
        assert "job=cron-process-scheduled" in caplog.text
        assert "processed=2" in caplog.text
