"""Shopping list model for managing grocery lists."""

import enum
from datetime import datetime

from sqlalchemy import Integer, DateTime, Enum
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

    Items are stored in the ShoppingListItem junction table (v2 schema).
    """

    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[ShoppingListStatus] = mapped_column(
        Enum(ShoppingListStatus), default=ShoppingListStatus.ACTIVE, nullable=False
    )
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="shopping_list"
    )
    shopping_list_items: Mapped[list["ShoppingListItem"]] = relationship(
        "ShoppingListItem", back_populates="shopping_list"
    )

    def __repr__(self) -> str:
        return f"<ShoppingList(id={self.id}, status={self.status.value})>"
