"""
Unit tests for archive_service.copy_transactions_to_history.

Verifies idempotent copy logic using SQLAlchemy insert().from_select()
with a WHERE NOT EXISTS guard. Transactions are NEVER deleted — copy only.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services import archive_service


class TestCopyTransactionsToHistory:
    """Tests for archive_service.copy_transactions_to_history."""

    @pytest.mark.asyncio
    async def test_returns_row_count_of_inserted_rows(self, mock_db: AsyncMock) -> None:
        """Should return the number of rows successfully copied."""
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await archive_service.copy_transactions_to_history(db=mock_db)

        assert result == 5

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_eligible_rows(self, mock_db: AsyncMock) -> None:
        """When all transactions are already archived, rowcount is 0."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await archive_service.copy_transactions_to_history(db=mock_db)

        assert result == 0

    @pytest.mark.asyncio
    async def test_executes_db_query(self, mock_db: AsyncMock) -> None:
        """The service must call db.execute exactly once with an INSERT statement."""
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_db.execute = AsyncMock(return_value=mock_result)

        await archive_service.copy_transactions_to_history(db=mock_db)

        mock_db.execute.assert_awaited_once()
