"""Preferences model for storing user dietary preferences."""

from sqlalchemy import Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Preference(Base, TimestampMixin):
    """Model for storing user preferences.

    Reserved for Phase 3 - dietary preferences.
    User can be "Erich", "L", or "household" for shared preferences.
    """

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user: Mapped[str] = mapped_column(String(50), nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<Preference(id={self.id}, user='{self.user}')>"
