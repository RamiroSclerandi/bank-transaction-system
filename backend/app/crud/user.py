"""CRUD operations for User."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.schemas.user import AdminUserCreate, CustomerUserCreate


class CRUDUser:
    """Data access layer for the User model."""

    async def get(self, db: AsyncSession, *, user_id: uuid.UUID) -> User | None:
        """
        Fetch a user by primary key.

        Args:
        ----
            db: Active async database session.
            user_id: The UUID of the user to fetch.

        Returns:
        -------
            The User instance or None if not found.

        """
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, db: AsyncSession, *, email: str) -> User | None:
        """
        Fetch a user by email address.

        Args:
        ----
            db: Active async database session.
            email: The email to look up.

        Returns:
        -------
            The User instance or None if not found.

        """
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_national_id(
        self, db: AsyncSession, *, national_id: int
    ) -> User | None:
        """
        Fetch a user by national ID number.

        Args:
        ----
            db: Active async database session.
            national_id: The national ID to look up.

        Returns:
        -------
            The User instance or None if not found.

        """
        result = await db.execute(select(User).where(User.national_id == national_id))
        return result.scalar_one_or_none()

    async def get_by_phone(self, db: AsyncSession, *, phone: int) -> User | None:
        """
        Fetch a user by phone number.

        Args:
        ----
            db: Active async database session.
            phone: The phone number to look up.

        Returns:
        -------
            The User instance or None if not found.

        """
        result = await db.execute(select(User).where(User.phone == phone))
        return result.scalar_one_or_none()

    async def create_admin(
        self,
        db: AsyncSession,
        *,
        data: AdminUserCreate,
    ) -> User:
        """
        Create a new admin user with a bcrypt-hashed password.
        The caller is responsible for ensuring the email does not already exist
        before calling this method (e.g. by calling get_by_email first).

        Args:
        ----
            db: Active async database session.
            data: Validated AdminUserCreate payload.

        Returns:
        -------
            The newly created User instance with role=admin.

        """
        user = User(
            id=uuid.uuid4(),
            name=data.name,
            email=data.email,
            password_hash=hash_password(data.password),
            national_id=data.national_id,
            phone=data.phone,
            role=UserRole.admin,
            registered_ip=data.registered_ip,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    async def is_admin(self, user: User) -> bool:
        """
        Check whether a user holds the admin role.

        Args:
        ----
            user: The User instance to check.

        Returns:
        -------
            True if the user's role is admin.

        """
        return user.role == UserRole.admin

    async def create_customer(
        self,
        db: AsyncSession,
        *,
        data: CustomerUserCreate,
    ) -> User:
        """
        Create a new customer user with a bcrypt-hashed password.
        The caller is responsible for ensuring the email does not already exist
        before calling this method.

        Args:
        ----
            db: Active async database session.
            data: Validated CustomerUserCreate payload.

        Returns:
        -------
            The newly created User instance with role=customer.

        """
        user = User(
            id=uuid.uuid4(),
            name=data.name,
            email=data.email,
            password_hash=hash_password(data.password),
            national_id=data.national_id,
            phone=data.phone,
            role=UserRole.customer,
            registered_ip=data.registered_ip,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user


crud_user = CRUDUser()
