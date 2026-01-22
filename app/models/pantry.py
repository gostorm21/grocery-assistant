"""Pantry model for tracking pantry items."""

from datetime import date

from sqlalchemy import Integer, String, Date, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class PantryItem(Base, TimestampMixin):
    """Model for tracking items in the pantry.

    Used in Phase 3 for pantry tracking and auto-reorder functionality.
    """

    __tablename__ = "pantry_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    auto_reorder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reorder_threshold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<PantryItem(id={self.id}, name='{self.item_name}')>"
