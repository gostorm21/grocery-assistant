"""SQLAlchemy base and helper utilities."""

import re
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


def normalize_recipe_name(name: str) -> str:
    """Normalize recipe names for matching.

    Converts to lowercase, strips punctuation, and collapses whitespace.
    This ensures "Chicken Tacos" == "chicken tacos!" == "Chicken  Tacos"

    Args:
        name: The recipe name to normalize.

    Returns:
        Normalized recipe name for consistent matching.
    """
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)  # Remove punctuation
    name = re.sub(r"\s+", " ", name).strip()  # Collapse whitespace
    return name
