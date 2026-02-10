"""Normalized ingredient model and junction tables."""

import re
from datetime import datetime

from sqlalchemy import Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


def normalize_ingredient_name(name: str) -> str:
    """Normalize ingredient names for matching.

    Converts to lowercase, strips punctuation, and collapses whitespace.
    """
    name = name.lower()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


class Ingredient(Base, TimestampMixin):
    """Single source of truth for each unique ingredient.

    Replaces BrandPreference — stores Kroger product ID, brand, and size
    alongside the ingredient identity.
    """

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    kroger_product_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preferred_size: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    recipe_ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        "RecipeIngredient", back_populates="ingredient"
    )
    shopping_list_items: Mapped[list["ShoppingListItem"]] = relationship(
        "ShoppingListItem", back_populates="ingredient"
    )

    def __init__(self, **kwargs):
        if "name" in kwargs and "normalized_name" not in kwargs:
            kwargs["normalized_name"] = normalize_ingredient_name(kwargs["name"])
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Ingredient(id={self.id}, name='{self.name}')>"


class RecipeIngredient(Base):
    """Junction table linking recipes to ingredients."""

    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipes.id"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredients.id"), nullable=False
    )
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prep_notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="recipe_ingredients")
    ingredient: Mapped["Ingredient"] = relationship(
        "Ingredient", back_populates="recipe_ingredients"
    )

    def __repr__(self) -> str:
        return f"<RecipeIngredient(recipe_id={self.recipe_id}, ingredient_id={self.ingredient_id})>"


class ShoppingListItem(Base):
    """Normalized shopping list items replacing JSON items array."""

    __tablename__ = "shopping_list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shopping_list_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shopping_lists.id"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredients.id"), nullable=False
    )
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    added_by: Mapped[str] = mapped_column(String(50), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    from_recipe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("recipes.id"), nullable=True
    )
    checked_off: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    shopping_list: Mapped["ShoppingList"] = relationship(
        "ShoppingList", back_populates="shopping_list_items"
    )
    ingredient: Mapped["Ingredient"] = relationship(
        "Ingredient", back_populates="shopping_list_items"
    )
    from_recipe: Mapped["Recipe | None"] = relationship("Recipe")

    def __repr__(self) -> str:
        return f"<ShoppingListItem(id={self.id}, ingredient_id={self.ingredient_id})>"
