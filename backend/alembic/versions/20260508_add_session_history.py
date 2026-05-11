"""
Add session_history table for session lifecycle audit trail.
- Revision ID: e5f6a7b8c9d0
- Revises: d4e5f6a7b8c9
    Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply the migration."""
    op.create_table(
        "session_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "event",
            sa.Enum("login", "logout", "expired", name="sessionevent"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_session_history_user_id", "session_history", ["user_id"])


def downgrade() -> None:
    """Revert the migration."""
    op.drop_index("ix_session_history_user_id", table_name="session_history")
    op.drop_table("session_history")
    op.execute("DROP TYPE IF EXISTS sessionevent")
