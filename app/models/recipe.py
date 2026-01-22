"""Recipe model for storing recipe information."""

from sqlalchemy import Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Recipe(Base, TimestampMixin):
    """Model for storing recipes."""

    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingredients: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cuisine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationship to recipe notes
    notes: Mapped[list["RecipeNote"]] = relationship(
        "RecipeNote", back_populates="recipe"
    )

    def __repr__(self) -> str:
        return f"<Recipe(id={self.id}, name='{self.name}')>"
