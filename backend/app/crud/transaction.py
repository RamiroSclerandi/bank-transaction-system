"""
CRUD operations for Transaction.
IMMUTABILITY CONTRACT: No method in this module issues UPDATE or DELETE
against the transactions table via customer-facing code paths.
The only mutations allowed are:
  - create()          — customer-facing, creates a new record.
  - update_status()   — internal-only, called by Lambda worker or webhook.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import (
    Transaction,
    TransactionMethod,
    TransactionStatus,
    TransactionType,
)
from app.schemas.transaction import TransactionListFilters


class CRUDTransaction:
    """Data access layer for the Transaction model."""

    async def get(
        self, db: AsyncSession, *, transaction_id: uuid.UUID
    ) -> Transaction | None:
        """
        Fetch a transaction by primary key.

        Args:
        ----
            db: Active async database session.
            transaction_id: The UUID of the transaction.

        Returns:
        -------
            The Transaction instance or None.

        """
        result = await db.execute(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        db: AsyncSession,
        *,
        source_card: uuid.UUID,
        origin_account: uuid.UUID,
        destination_account: str,
        amount: Decimal,
        transaction_type: TransactionType,
        method: TransactionMethod,
        status: TransactionStatus,
        scheduled_for: datetime | None = None,
        reversal_of: uuid.UUID | None = None,
    ) -> Transaction:
        """
        Persist a new transaction record.

        Args:
        ----
            db: Active async database session.
            source_card: Card UUID used to initiate the transaction.
            origin_account: Account UUID from which funds are debited.
            destination_account: Target account identifier or IBAN.
            amount: Transaction amount (must be > 0).
            transaction_type: national or international.
            method: debit or credit (derived from source card).
            status: Initial lifecycle status.
            scheduled_for: Optional future execution datetime.
            reversal_of: UUID of the original transaction if this is a reversal.

        Returns:
        -------
            The newly created, persisted Transaction.

        """
        transaction = Transaction(
            source_card=source_card,
            origin_account=origin_account,
            destination_account=destination_account,
            amount=amount,
            type=transaction_type,
            method=method,
            status=status,
            scheduled_for=scheduled_for,
            reversal_of=reversal_of,
        )
        db.add(transaction)
        await db.flush()
        await db.refresh(transaction)
        return transaction

    async def update_status(
        self,
        db: AsyncSession,
        *,
        transaction_id: uuid.UUID,
        new_status: TransactionStatus,
        expected_current_status: TransactionStatus,
    ) -> bool:
        """
        Atomically transition a transaction to a new status.
        Uses an optimistic lock pattern: the UPDATE is conditioned on the
        current status matching `expected_current_status`. If the row was
        already transitioned by another worker, returns False.

        Args:
        ----
            db: Active async database session.
            transaction_id: The UUID of the transaction to update.
            new_status: The target status.
            expected_current_status: The status the row must currently have.

        Returns:
        -------
            True if the row was updated, False if the condition was not met.

        """
        result = await db.execute(
            update(Transaction)
            .where(
                and_(
                    Transaction.id == transaction_id,
                    Transaction.status == expected_current_status,
                )
            )
            .values(status=new_status)
        )
        return result.rowcount > 0  # type: ignore[attr-defined, no-any-return]

    async def list_by_account(
        self,
        db: AsyncSession,
        *,
        account_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Transaction]:
        """
        List transactions for a specific account (customer view).

        Args:
        ----
            db: Active async database session.
            account_id: Filter by this origin account UUID.
            limit: Maximum number of records to return.
            offset: Pagination offset.

        Returns:
        -------
            A list of Transaction instances ordered by creation date descending.

        """
        result = await db.execute(
            select(Transaction)
            .where(Transaction.origin_account == account_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_filtered(
        self, db: AsyncSession, *, filters: TransactionListFilters
    ) -> list[Transaction]:
        """
        List transactions with optional filters (admin view).

        Args:
        ----
            db: Active async database session.
            filters: Query parameters for filtering.

        Returns:
        -------
            A list of Transaction instances matching the criteria.

        """
        query = select(Transaction)

        if filters.user_id:
            # Resolve user_id → account.id via subquery (1-to-1 relationship)
            account_subq = (
                select(Account.id)
                .where(Account.user_id == filters.user_id)
                .scalar_subquery()
            )
            query = query.where(Transaction.origin_account == account_subq)

        if filters.account_id:
            query = query.where(Transaction.origin_account == filters.account_id)
        if filters.status:
            query = query.where(Transaction.status == filters.status)
        if filters.type:
            query = query.where(Transaction.type == filters.type)
        if filters.date_from:
            query = query.where(Transaction.created_at >= filters.date_from)
        if filters.date_to:
            query = query.where(Transaction.created_at <= filters.date_to)

        query = (
            query.order_by(Transaction.created_at.desc())
            .limit(filters.limit)
            .offset(filters.offset)
        )
        result = await db.execute(query)
        return list(result.scalars().all())


crud_transaction = CRUDTransaction()
