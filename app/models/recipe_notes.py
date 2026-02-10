"""Recipe notes model for storing cooking feedback."""

import enum
from datetime import datetime

from sqlalchemy import Integer, String, Text, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, normalize_recipe_name


class NoteType(enum.Enum):
    """Type of recipe note."""

    INGREDIENT_CHANGE = "ingredient_change"
    TECHNIQUE = "technique"
    TIMING = "timing"
    GENERAL = "general"


class NoteOutcome(enum.Enum):
    """Outcome of the change described in the note."""

    BETTER = "better"
    WORSE = "worse"
    NEUTRAL = "neutral"


class RecipeNote(Base):
    """Model for storing recipe notes and cooking feedback."""

    __tablename__ = "recipe_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recipes.id"), nullable=True
    )
    recipe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    recipe_name_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user: Mapped[str] = mapped_column(String(50), nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[NoteType] = mapped_column(
        Enum(NoteType), default=NoteType.GENERAL, nullable=False
    )
    outcome: Mapped[NoteOutcome] = mapped_column(
        Enum(NoteOutcome), default=NoteOutcome.NEUTRAL, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationship to recipe
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="notes")

    def __init__(self, **kwargs):
        """Initialize recipe note, auto-normalizing recipe name."""
        if "recipe_name" in kwargs and "recipe_name_normalized" not in kwargs:
            kwargs["recipe_name_normalized"] = normalize_recipe_name(
                kwargs["recipe_name"]
            )
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<RecipeNote(id={self.id}, recipe='{self.recipe_name}', type={self.note_type.value})>"
