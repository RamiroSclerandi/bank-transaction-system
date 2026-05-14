"""
Archive service - copies completed/failed transactions to transaction_history.

Transactions are NEVER deleted. This is a copy-only operation.
Idempotency is enforced via a WHERE NOT EXISTS subquery.
"""

from sqlalchemy import String, cast, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Integer

from app.models.account import Account
from app.models.transaction import Transaction, TransactionStatus
from app.models.transaction_history import TransactionHistory


async def copy_transactions_to_history(db: AsyncSession) -> int:
    """
    Copy all eligible transactions (completed/failed) to transaction_history.

    Idempotent - transactions already present in transaction_history are skipped
    via the WHERE NOT EXISTS guard. Transactions are NEVER deleted.

    Args:
    ----
        db: Active async database session.

    Returns:
    -------
        Number of rows inserted.

    """
    # Subquery for WHERE NOT EXISTS guard
    subq = (
        select(1)
        .where(TransactionHistory.transaction_id == Transaction.id)
        .correlate(Transaction)
    )

    # Denormalized SELECT from transactions + accounts
    # func.gen_random_uuid() is used explicitly so each row gets its own UUID.
    # Using the ORM insert() would cause SQLAlchemy to evaluate default=uuid.uuid4
    # once at statement-compile time and bind the same UUID for every row,
    # triggering UniqueViolationError on idempotent re-runs.
    select_stmt = (
        select(
            func.gen_random_uuid(),
            Transaction.id,
            Account.user_id,
            Transaction.origin_account,
            Transaction.destination_account,
            Transaction.amount,
            cast(Transaction.type, String),
            cast(Transaction.method, String),
            cast(Transaction.status, String),
            cast(func.extract("year", Transaction.created_at), Integer),
            cast(func.extract("month", Transaction.created_at), Integer),
            cast(func.extract("day", Transaction.created_at), Integer),
            cast(func.extract("hour", Transaction.created_at), Integer),
            Transaction.created_at,
            func.now(),
        )
        .select_from(Transaction)
        .join(Account, Transaction.origin_account == Account.id)
        .where(
            Transaction.status.in_(
                [TransactionStatus.completed, TransactionStatus.failed]
            ),
            ~subq.exists(),
        )
    )

    # Compile the INSERT INTO ... SELECT ... statement
    # The columns must match the exact order of the select_stmt
    archive_stmt = insert(TransactionHistory).from_select(
        [
            "id",
            "transaction_id",
            "user_id",
            "origin_account_id",
            "destination_account",
            "amount",
            "type",
            "method",
            "status",
            "year",
            "month",
            "day",
            "hour",
            "created_at",
            "archived_at",
        ],
        select_stmt,
    )

    async with db.begin():
        result = await db.execute(archive_stmt)
    return int(result.rowcount)  # type: ignore[attr-defined]
