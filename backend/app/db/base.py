"""SQLAlchemy declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Shared declarative base for all SQLAlchemy models.
    All models must inherit from this class so that Alembic can discover
    the full metadata graph for auto-generating migrations.
    """
