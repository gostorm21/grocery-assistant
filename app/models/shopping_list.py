"""Shopping list model for managing grocery lists."""

import enum
from datetime import datetime

from sqlalchemy import Integer, DateTime, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class ShoppingListStatus(enum.Enum):
    """Status of a shopping list."""

    ACTIVE = "active"
    ORDERED = "ordered"


class ShoppingList(Base, TimestampMixin):
    """Model for storing shopping lists.

    Only ONE list can have status='active' at a time.
    This is enforced via a partial unique index in the database migration.

    Item structure (JSON):
    {
        "name": "Milk",
        "quantity": 1,
        "unit": "gallon",
        "brand": "Organic Valley",
        "added_by": "Erich",
        "added_at": "2026-01-20T10:30:00"
    }
    """

    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[ShoppingListStatus] = mapped_column(
        Enum(ShoppingListStatus), default=ShoppingListStatus.ACTIVE, nullable=False
    )
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationship to conversations
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="shopping_list"
    )

    def __repr__(self) -> str:
        item_count = len(self.items) if self.items else 0
        return f"<ShoppingList(id={self.id}, status={self.status.value}, items={item_count})>"
