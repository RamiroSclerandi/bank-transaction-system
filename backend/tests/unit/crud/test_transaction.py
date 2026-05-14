"""
Unit tests for CRUDTransaction.get_due_ids.

Smoke tests: verify that the method forwards the db.execute result correctly.
The WHERE-clause filtering logic (status='scheduled', scheduled_for <= now())
is intentionally not exercised here — mocking db.execute bypasses SQLAlchemy's
query compilation entirely. That behavior belongs in integration tests with a
real database session.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.crud.transaction import CRUDTransaction


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
