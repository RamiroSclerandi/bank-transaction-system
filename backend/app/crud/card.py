"""CRUD operations for Card."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.card import Card, CardType


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
            select(Card).options(joinedload(Card.account)).where(Card.id == card_id)  # type: ignore[arg-type]
        )
        return result.scalar_one_or_none()

    async def get_by_hmac(self, db: AsyncSession, *, number_hmac: str) -> Card | None:
        """
        Fetch a card by its PAN HMAC digest, eagerly loading its account.
        Used for the get-or-create lookup during transaction creation.

        Args:
        ----
            db: Active async database session.
            number_hmac: HMAC-SHA256 hex digest of the raw PAN digits.

        Returns:
        -------
            The Card instance with the related Account loaded, or None.

        """
        result = await db.execute(
            select(Card)
            .options(joinedload(Card.account))  # type: ignore[arg-type]
            .where(Card.number_hmac == number_hmac)
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

    async def create(
        self,
        db: AsyncSession,
        *,
        account_id: uuid.UUID,
        card_type: CardType,
        number_hmac: str,
        number_last4: str,
        expiration_month: int,
        expiration_year: int,
    ) -> Card:
        """
        Persist a new card record.

        Args:
        ----
            db: Active async database session.
            account_id: The owning account UUID.
            card_type: debit or credit.
            number_hmac: HMAC-SHA256 hex digest of the raw PAN digits.
            number_last4: Last 4 digits of the PAN (plain text, safe to display).
            expiration_month: 1-12.
            expiration_year: 2-digit year (e.g. 28 for 2028).

        Returns:
        -------
            The newly created Card instance.

        """
        card = Card(
            id=uuid.uuid4(),
            account_id=account_id,
            card_type=card_type,
            number_hmac=number_hmac,
            number_last4=number_last4,
            expiration_month=expiration_month,
            expiration_year=expiration_year,
        )
        db.add(card)
        await db.flush()
        await db.refresh(card)
        return card


crud_card = CRUDCard()
