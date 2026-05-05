"""CRUD operations for Card."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.card import Card


class CRUDCard:
    """Data access layer for the Card model."""

    async def get(self, db: AsyncSession, *, card_id: uuid.UUID) -> Card | None:
        """
        Fetch a card by primary key, eagerly loading its account.

        Args:
        ----
            db: Active async database session.
            card_id: The UUID of the card.

        Returns:
        -------
            The Card instance with the related Account loaded, or None.

        """
        result = await db.execute(
            select(Card).options(joinedload(Card.account)).where(Card.id == card_id)
        )
        return result.scalar_one_or_none()

    async def get_all_by_account(
        self, db: AsyncSession, *, account_id: uuid.UUID
    ) -> list[Card]:
        """
        Fetch all cards for a given account.

        Args:
        ----
            db: Active async database session.
            account_id: The UUID of the account.

        Returns:
        -------
            A list of Card instances belonging to the account.

        """
        result = await db.execute(select(Card).where(Card.account_id == account_id))
        return list(result.scalars().all())


crud_card = CRUDCard()
