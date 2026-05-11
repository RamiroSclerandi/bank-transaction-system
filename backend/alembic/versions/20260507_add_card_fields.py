"""
Add card PAN and security fields to the cards table.
- Revision ID: c3d4e5f6a7b8
- Revises: b2c3d4e5f6a7
    Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    """Apply the migration."""
    op.add_column("cards", sa.Column("number_hmac", sa.String(64), nullable=False))
    op.add_column("cards", sa.Column("number_last4", sa.String(4), nullable=False))
    op.add_column("cards", sa.Column("expiration_month", sa.Integer(), nullable=False))
    op.add_column("cards", sa.Column("expiration_year", sa.Integer(), nullable=False))

    op.create_unique_constraint("uq_cards_number_hmac", "cards", ["number_hmac"])
    op.create_check_constraint(
        "ck_cards_expiration_month",
        "cards",
        "expiration_month >= 1 AND expiration_month <= 12",
    )
    op.create_check_constraint(
        "ck_cards_expiration_year",
        "cards",
        "expiration_year >= 26",
    )


def downgrade():
    """Revert the migration."""
    op.drop_constraint("ck_cards_expiration_year", "cards", type_="check")
    op.drop_constraint("ck_cards_expiration_month", "cards", type_="check")
    op.drop_constraint("uq_cards_number_hmac", "cards", type_="unique")
    op.drop_column("cards", "expiration_year")
    op.drop_column("cards", "expiration_month")
    op.drop_column("cards", "number_last4")
    op.drop_column("cards", "number_hmac")
