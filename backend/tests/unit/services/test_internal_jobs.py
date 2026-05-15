"""
Unit tests for internal daily job endpoints.

Tests POST /api/v1/internal/jobs/archive-transactions and
POST /api/v1/internal/jobs/daily-backup, verifying:
- Auth enforcement (403 without X-Internal-Api-Key)
- Correct delegation to archive_service / backup_service via background tasks
- 202 Accepted response with accepted body
- Background function logging via caplog
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.api_v1.endpoints.internal import (
    _run_archive_in_background,
    _run_daily_backup_in_background,
    router,
)
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
    async def test_returns_202_and_schedules_archive(
        self,
        app: FastAPI,
        internal_key: str,
        mock_archive_service: AsyncMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """Valid request must return 202 and schedule archive in background."""
        mock_archive_service.return_value = 12
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/jobs/archive-transactions",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "job": "archive-transactions"}
        mock_archive_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_archive(
        self,
        app: FastAPI,
        internal_key: str,
        mock_archive_service: AsyncMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """When archive returns 0, must still return 202 accepted."""
        mock_archive_service.return_value = 0
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/internal/jobs/archive-transactions",
                headers={"X-Internal-Api-Key": internal_key},
            )

        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "job": "archive-transactions"}
        mock_archive_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_background_logs_success(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_archive_service: AsyncMock,
        mock_internal_async_session_local: AsyncMock,
    ) -> None:
        """_run_archive_in_background must log completion with rows_archived count."""
        mock_archive_service.return_value = 5

        with caplog.at_level(logging.INFO, logger="app.api.api_v1.endpoints.internal"):
            await _run_archive_in_background()

        assert "internal_job_completed" in caplog.text
        assert "status=success" in caplog.text
        assert "rows_archived=5" in caplog.text


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
    async def test_returns_202_and_schedules_backup(
        self,
        app: FastAPI,
        internal_key: str,
        mock_backup_service: AsyncMock,
    ) -> None:
        """Valid request must return 202 and schedule backup in background."""
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

        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "job": "daily-backup"}
        mock_backup_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_backup_background_logs_success(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_backup_service: AsyncMock,
    ) -> None:
        """_run_daily_backup_in_background must log success with snapshot details."""
        mock_backup_service.return_value = {
            "snapshot_id": "daily-snapshot-2026-05-14",
            "status": "completed",
        }

        with caplog.at_level(logging.INFO, logger="app.api.api_v1.endpoints.internal"):
            await _run_daily_backup_in_background()

        assert "internal_job_completed" in caplog.text
        assert "status=success" in caplog.text
