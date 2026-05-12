"""
Unit tests for backup_service.execute_daily_backup.

Verifies environment-based branching (dev = pg_dump, prod = boto3 RDS snapshot).
AWS-specific: duplicate snapshot ClientError must be safely caught (idempotency).
"""

from datetime import date
from unittest.mock import MagicMock

import botocore.exceptions  # type: ignore[import-untyped]
import pytest
from app.services import backup_service


class TestExecuteDailyBackupDevelopment:
    """Tests for backup_service in development environment."""

    @pytest.fixture(autouse=True)
    def setup_dev_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Configure settings for development environment."""
        monkeypatch.setattr(
            "app.services.backup_service.settings",
            MagicMock(
                ENVIRONMENT="development",
                DATABASE_URL="postgresql+asyncpg://user:pass@localhost/testdb",
            ),
        )

    @pytest.mark.asyncio
    async def test_dev_calls_pg_dump_with_correct_filename(
        self, mock_subprocess_run: MagicMock, mock_os_makedirs: MagicMock
    ) -> None:
        """In development, pg_dump is called with the
        daily-snapshot-YYYY-MM-DD filename."""
        result = await backup_service.execute_daily_backup()

        today = date.today().isoformat()
        expected_filename = f"daily-snapshot-{today}.sql"
        assert result["snapshot_id"] == expected_filename
        assert result["status"] == "completed"
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args[0][0]
        assert "pg_dump" in call_args
        assert expected_filename in call_args[-1]

    @pytest.mark.asyncio
    async def test_dev_creates_backup_directory(
        self, mock_subprocess_run: MagicMock, mock_os_makedirs: MagicMock
    ) -> None:
        """In development, the db_backups directory is created if it doesn't exist."""
        await backup_service.execute_daily_backup()

        mock_os_makedirs.assert_called_once()
        call_kwargs = mock_os_makedirs.call_args
        assert call_kwargs[1].get("exist_ok") is True


class TestExecuteDailyBackupProduction:
    """Tests for backup_service in production environment."""

    @pytest.fixture(autouse=True)
    def setup_prod_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Configure settings for production environment."""
        monkeypatch.setattr(
            "app.services.backup_service.settings",
            MagicMock(
                ENVIRONMENT="production",
                AWS_REGION="eu-west-1",
                AWS_RDS_INSTANCE_IDENTIFIER="my-db-instance",
            ),
        )

    @pytest.mark.asyncio
    async def test_prod_calls_rds_create_snapshot_with_correct_name(
        self, mock_boto3_client: MagicMock
    ) -> None:
        """In production, boto3 RDS create_db_snapshot is called with
        daily-snapshot-YYYY-MM-DD."""
        mock_boto3_client.create_db_snapshot.return_value = {
            "DBSnapshot": {
                "DBSnapshotIdentifier": "daily-snapshot-2026-05-11",
                "Status": "creating",
            }
        }

        result = await backup_service.execute_daily_backup()

        today = date.today().isoformat()
        expected_snapshot_id = f"daily-snapshot-{today}"
        mock_boto3_client.create_db_snapshot.assert_called_once_with(
            DBSnapshotIdentifier=expected_snapshot_id,
            DBInstanceIdentifier="my-db-instance",
        )
        assert result["snapshot_id"] == expected_snapshot_id
        assert result["status"] == "creating"

    @pytest.mark.asyncio
    async def test_prod_handles_duplicate_snapshot_idempotently(
        self, mock_boto3_client: MagicMock
    ) -> None:
        """In production, a DBSnapshotAlreadyExists error is
        caught and treated as success."""
        mock_boto3_client.create_db_snapshot.side_effect = (
            botocore.exceptions.ClientError(
                {
                    "Error": {
                        "Code": "DBSnapshotAlreadyExists",
                        "Message": "Already exists",
                    }
                },
                "CreateDBSnapshot",
            )
        )

        result = await backup_service.execute_daily_backup()

        today = date.today().isoformat()
        assert result["snapshot_id"] == f"daily-snapshot-{today}"
        assert result["status"] == "already_exists"
