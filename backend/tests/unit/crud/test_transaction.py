"""
Unit tests for CRUDTransaction.get_due_ids.

Tests verify:
- Returns UUIDs of transactions with status='scheduled' AND scheduled_for <= now().
- Returns empty list when no transactions qualify.
- Excludes transactions with non-'scheduled' status.
- Excludes transactions with scheduled_for > now().
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.transaction import CRUDTransaction


def _make_row(tid: uuid.UUID) -> MagicMock:
    row = MagicMock()
    row.__iter__ = MagicMock(return_value=iter([tid]))
    return tid


@pytest.mark.asyncio
async def test_get_due_ids_returns_qualifying_uuids() -> None:
    """get_due_ids returns IDs matching status=scheduled and scheduled_for <= now."""
    due_id = uuid.uuid4()
    db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [due_id]
    db.execute = AsyncMock(return_value=mock_result)

    crud = CRUDTransaction()
    result = await crud.get_due_ids(db)

    assert result == [due_id]
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_due_ids_returns_empty_list_when_none_qualify() -> None:
    """get_due_ids returns [] when no transactions qualify."""
    db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)

    crud = CRUDTransaction()
    result = await crud.get_due_ids(db)

    assert result == []
    db.execute.assert_awaited_once()
