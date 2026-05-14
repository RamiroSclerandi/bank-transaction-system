"""Shared fixtures for CRUD unit tests."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_crud_user_hash_password() -> Generator[MagicMock, None, None]:
    """Patch hash_password inside app.crud.user."""
    with patch("app.crud.user.hash_password", return_value="hashed") as mock:
        yield mock
