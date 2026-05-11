"""
Add index on sessions.token_hash.
- Revision ID: b2c3d4e5f6a7
- Revises: a1b2c3d4e5f6
    Create Date: 2026-05-07
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    """Apply the migration."""
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"])


def downgrade():
    """Revert the migration."""
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
