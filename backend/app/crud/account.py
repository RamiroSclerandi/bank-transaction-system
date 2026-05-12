"""CRUD operations for Account."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account


class CRUDAccount:
    """Data access layer for the Account model."""

    async def get(self, db: AsyncSession, *, account_id: uuid.UUID) -> Account | None:
        """
        Fetch an account by primary key.

        Args:
        ----
            db: Active async database session.
            account_id: The UUID of the account.

        Returns:
        -------
            The Account instance or None.

        """
        result = await db.execute(select(Account).where(Account.id == account_id))
        return result.scalar_one_or_none()

    async def get_by_user(
        self, db: AsyncSession, *, user_id: uuid.UUID
    ) -> Account | None:
        """
        Fetch the account belonging to a given user.

        Args:
        ----
            db: Active async database session.
            user_id: The owner's user UUID.

        Returns:
        -------
            The Account instance or None.

        """
        result = await db.execute(select(Account).where(Account.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_with_lock(
        self, db: AsyncSession, *, account_id: uuid.UUID
    ) -> Account | None:
        """
        Fetch an account with a SELECT FOR UPDATE row lock. This must be called
        inside an open transaction to ensure atomicity of balance check + deduction.

        Args:
        ----
            db: Active async database session with an open transaction.
            account_id: The UUID of the account to lock.

        Returns:
        -------
            The Account instance or None.

        """
        result = await db.execute(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def deduct_balance(
        self, db: AsyncSession, *, account: Account, amount: Decimal
    ) -> None:
        """
        Atomically deduct amount from account balance, must be called inside
        a transaction that holds a row lock on the account (obtained via get_with_lock).

        Args:
        ----
            db: Active async database session.
            account: The locked Account instance.
            amount: The amount to deduct (must be > 0).

        """
        account.balance = account.balance - amount
        db.add(account)

    async def add_balance(
        self, db: AsyncSession, *, account: Account, amount: Decimal
    ) -> None:
        """
        Add amount to account balance. Must be called inside a transaction
        that holds a row lock on the account (obtained via get_with_lock).

        Args:
        ----
            db: Active async database session.
            account: The locked Account instance.
            amount: The amount to credit (must be > 0).

        """
        account.balance = account.balance + amount
        db.add(account)

    async def create(self, db: AsyncSession, *, user_id: uuid.UUID) -> Account:
        """
        Create a new bank account for a user with zero initial balance.

        Args:
        ----
            db: Active async database session.
            user_id: The UUID of the owning user.

        Returns:
        -------
            The newly created Account instance.

        """
        account = Account(
            id=uuid.uuid4(),
            user_id=user_id,
            balance=Decimal("0.0000"),
        )
        db.add(account)
        await db.flush()
        await db.refresh(account)
        return account


crud_account = CRUDAccount()
