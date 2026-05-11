"""
Seed script: create the first admin user.

Run this once after running `alembic upgrade head` to create the initial
admin user that can be used to test the backoffice endpoints. Admins do not
have a bank account by default. Use POST /admin/accounts to create one if needed.

Usage:
    cd backend
    python scripts/seed_admin.py
Environment:
    Reads DATABASE_URL from the .env file (same as the app).
"""

import asyncio
import os
import uuid

from app.core.config import settings
from app.core.security import hash_password
from app.models.user import User, UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Admin user details ──
# Change these values before running in a shared environment.
ADMIN_EMAIL = "admin@bankdev.local"
ADMIN_NAME = "Dev Admin"
ADMIN_DNI = 99999999
ADMIN_PHONE = 600000001

# Password is read from the environment to avoid hardcoding it in source.
_DEV_DEFAULT_PASSWORD = "change-me-before-production"  # noqa: S105
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", _DEV_DEFAULT_PASSWORD)


async def seed(session: AsyncSession):
    """
    Insert the admin user and account if they do not already exist.

    Args:
    ----
        session: Active async database session.

    """
    result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
    existing = result.scalars().first()

    if existing is not None:
        print(f"[seed] Admin user '{ADMIN_EMAIL}' already exists — skipping.")
        return

    admin_id = uuid.uuid4()
    user = User(
        id=admin_id,
        name=ADMIN_NAME,
        national_id=ADMIN_DNI,
        email=ADMIN_EMAIL,
        phone=ADMIN_PHONE,
        password_hash=hash_password(ADMIN_PASSWORD),
        role=UserRole.admin,
        registered_ip=None,
    )

    session.add(user)
    await session.commit()

    print(f"[seed] Created admin user: id={admin_id}  email={ADMIN_EMAIL}")
    print()
    print("  Next step: log in with:")
    print(
        f"    POST /admin/auth/login"
        f"  {{ email: '{ADMIN_EMAIL}', password: '<your_password>' }}"
    )
    print()
    print("  To create a bank account for this admin:")
    print(f"    POST /admin/accounts  {{ user_id: '{admin_id}' }}")


async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with SessionLocal() as session:
        await seed(session)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
