"""
Unit tests for internal daily job endpoints.

Tests POST /api/v1/internal/jobs/archive-transactions and
POST /api/v1/internal/jobs/daily-backup, verifying:
- Auth enforcement (403 without X-Internal-Api-Key)
- Correct delegation to archive_service / backup_service
- Response format
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.api_v1.endpoints.internal import router
from fastapi import FastAPI
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


class TestArchiveTransactionsEndpoint:
    """Tests for POST /api/v1/internal/jobs/archive-transactions."""

    @pytest.mark.asyncio
    async def test_returns_403_without_internal_key(self, app: FastAPI) -> None:
        """Request without X-Internal-Api-Key must return 403."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/internal/jobs/archive-transactions")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_200_with_archived_count(
        self, app: FastAPI, internal_key: str, mock_archive_service: AsyncMock
    ) -> None:
        """Valid request should call archive_service and return rows_archived."""
        mock_archive_service.return_value = 12
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/jobs/archive-transactions",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["rows_archived"] == 12

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_archive(
        self, app: FastAPI, internal_key: str, mock_archive_service: AsyncMock
    ) -> None:
        """When archive returns 0, the response must reflect rows_archived=0."""
        mock_archive_service.return_value = 0
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/jobs/archive-transactions",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 200
        assert response.json()["rows_archived"] == 0


class TestDailyBackupEndpoint:
    """Tests for POST /api/v1/internal/jobs/daily-backup."""

    @pytest.mark.asyncio
    async def test_returns_403_without_internal_key(self, app: FastAPI) -> None:
        """Request without X-Internal-Api-Key must return 403."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/v1/internal/jobs/daily-backup")

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_returns_200_with_snapshot_info(
        self, app: FastAPI, internal_key: str, mock_backup_service: AsyncMock
    ) -> None:
        """Valid request should call backup_service and return snapshot_id + status."""
        mock_backup_service.return_value = {
            "snapshot_id": "daily-snapshot-2026-05-11",
            "status": "creating",
        }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/jobs/daily-backup",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["snapshot_id"] == "daily-snapshot-2026-05-11"
        assert data["status"] == "creating"
