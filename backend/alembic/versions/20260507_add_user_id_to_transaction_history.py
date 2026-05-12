"""
Add user_id to the transaction_history table.
- Revision ID: d4e5f6a7b8c9
- Revises: c3d4e5f6a7b8
    Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    """Apply the migration."""
    op.add_column(
        "transaction_history",
        sa.Column("user_id", sa.UUID(), nullable=False),
    )


def downgrade():
    """Revert the migration."""
    op.drop_column("transaction_history", "user_id")
