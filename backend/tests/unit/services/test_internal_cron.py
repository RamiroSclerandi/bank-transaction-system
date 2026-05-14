"""
Unit tests for POST /api/v1/internal/cron/process-scheduled.

Tests verify:
- 200 with correct summary (2 IDs processed)
- 200 with all zeros (empty run)
- 409 from service counted as skipped
- 403 without valid API key
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.api_v1.endpoints.internal import router
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
    ) -> None:
        """Valid request with 2 due IDs returns 200 with correct summary."""
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

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["processed"] == 2
        assert data["skipped"] == 0
        assert data["errors"] == 0

    @pytest.mark.asyncio
    async def test_empty_run_returns_all_zeros(
        self,
        app: FastAPI,
        internal_key: str,
        mock_internal_crud_transaction: MagicMock,
        mock_internal_transaction_service: MagicMock,
    ) -> None:
        """When no due IDs, response must be all zeros."""
        mock_internal_crud_transaction.get_due_ids = AsyncMock(return_value=[])
        mock_internal_transaction_service.process_scheduled_transaction = AsyncMock()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/cron/process-scheduled",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data == {"total": 0, "processed": 0, "skipped": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_409_from_service_counted_as_skipped(
        self,
        app: FastAPI,
        internal_key: str,
        mock_internal_crud_transaction: MagicMock,
        mock_internal_transaction_service: MagicMock,
    ) -> None:
        """When service raises HTTPException(409), it must be counted as skipped."""
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

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["processed"] == 0
        assert data["skipped"] == 1
        assert data["errors"] == 0
