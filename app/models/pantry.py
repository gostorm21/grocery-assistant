"""Pantry model for tracking pantry items."""

from datetime import date

from sqlalchemy import Integer, String, Date, Float, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class PantryItem(Base, TimestampMixin):
    """Model for tracking items in the pantry.

    Links to Ingredient for Kroger mapping and brand preferences.
    """

    __tablename__ = "pantry_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ingredient_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ingredients.id"), nullable=True
    )
    last_purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    auto_reorder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reorder_threshold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationship to ingredient
    ingredient = relationship("Ingredient", backref="pantry_items")

    def __repr__(self) -> str:
        return f"<PantryItem(id={self.id}, name='{self.item_name}')>"
