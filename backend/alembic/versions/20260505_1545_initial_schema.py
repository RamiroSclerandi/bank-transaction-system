"""
Initial schema.
- Revision ID: a1b2c3d4e5f6
- Revises:
    Create Date: 2026-05-05 15:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    """Apply the migration."""
    # ── users ───
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("national_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.BigInteger(), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "customer", name="userrole"),
            nullable=False,
        ),
        sa.Column("registered_ip", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("national_id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )

    # ── sessions ───
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_sessions_user_id"),
    )

    # ── audit_logs ──
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "action",
            sa.Enum("login", "logout", "login_failed", name="auditlogaction"),
            nullable=False,
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── accounts ──
    op.create_table(
        "accounts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("balance", sa.Numeric(19, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # ── cards ──
    op.create_table(
        "cards",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column(
            "card_type",
            sa.Enum("debit", "credit", name="cardtype"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── transactions ──
    op.create_table(
        "transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_card", sa.UUID(), nullable=False),
        sa.Column("origin_account", sa.UUID(), nullable=False),
        sa.Column("destination_account", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column(
            "type",
            sa.Enum("national", "international", name="transactiontype"),
            nullable=False,
        ),
        sa.Column(
            "method",
            sa.Enum("debit", "credit", name="transactionmethod"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "completed",
                "failed",
                "scheduled",
                "processing",
                name="transactionstatus",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column(
            "reversal_of",
            sa.UUID(),
            nullable=True,
            comment="References the original transaction when this is a reversal.",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        sa.ForeignKeyConstraint(["source_card"], ["cards.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["origin_account"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of"], ["transactions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_transactions_status_scheduled_for",
        "transactions",
        ["status", "scheduled_for"],
    )
    op.create_index(
        "ix_transactions_origin_account_created_at",
        "transactions",
        ["origin_account", "created_at"],
    )
    op.create_index(
        "ix_transactions_status_type",
        "transactions",
        ["status", "type"],
    )

    # ── transaction_history ──
    op.create_table(
        "transaction_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=False),
        sa.Column("origin_account_id", sa.UUID(), nullable=False),
        sa.Column("destination_account", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    """Revert the migration."""
    op.drop_table("transaction_history")
    op.drop_index("ix_transactions_status_type", table_name="transactions")
    op.drop_index(
        "ix_transactions_origin_account_created_at", table_name="transactions"
    )
    op.drop_index("ix_transactions_status_scheduled_for", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("cards")
    op.drop_table("accounts")
    op.drop_table("audit_logs")
    op.drop_table("sessions")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS transactionstatus")
    op.execute("DROP TYPE IF EXISTS transactionmethod")
    op.execute("DROP TYPE IF EXISTS transactiontype")
    op.execute("DROP TYPE IF EXISTS cardtype")
    op.execute("DROP TYPE IF EXISTS auditlogaction")
    op.execute("DROP TYPE IF EXISTS userrole")
