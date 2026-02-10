"""v2 schema: normalized ingredients, junction tables, event log, kroger tokens.

Revision ID: 002
Revises: 001
Create Date: 2026-02-10

Fresh start — no data migration needed (v1 deployment has minimal data).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Create new tables ===

    # Ingredients — single source of truth for each unique ingredient
    op.create_table(
        "ingredients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("kroger_product_id", sa.String(length=255), nullable=True),
        sa.Column("preferred_brand", sa.String(length=255), nullable=True),
        sa.Column("preferred_size", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )

    # Recipe ingredients junction table
    op.create_table(
        "recipe_ingredients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("prep_notes", sa.String(length=255), nullable=True),
        sa.Column("optional", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Shopping list items — normalized replacement for JSON items array
    op.create_table(
        "shopping_list_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("shopping_list_id", sa.Integer(), nullable=False),
        sa.Column("ingredient_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("added_by", sa.String(length=50), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.Column("from_recipe_id", sa.Integer(), nullable=True),
        sa.Column("checked_off", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["shopping_list_id"], ["shopping_lists.id"]),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredients.id"]),
        sa.ForeignKeyConstraint(["from_recipe_id"], ["recipes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Event log for audit trail
    op.create_table(
        "event_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column(
            "action_type",
            sa.Enum(
                "add_item", "remove_item", "clear_list", "finalize_order",
                "update_ingredient", "add_recipe", "add_recipe_note",
                "add_meal", "remove_meal", "generate_list", "complete_meal_plan",
                "update_preference", "add_pantry_item", "update_pantry_item",
                "remove_pantry_item", "resolve_kroger", "confirm_kroger",
                "add_to_cart", "check_off_item", "read_context",
                name="actiontype",
            ),
            nullable=False,
        ),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("related_ids", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Kroger tokens — single-row table for OAuth persistence
    op.create_table(
        "kroger_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("access_token", sa.String(length=2000), nullable=True),
        sa.Column("refresh_token", sa.String(length=2000), nullable=True),
        sa.Column("token_expiry", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # === Modify existing tables ===

    # Add title column to recipe_notes
    op.add_column("recipe_notes", sa.Column("title", sa.String(length=255), nullable=True))

    # Drop items JSON column from shopping_lists (replaced by shopping_list_items)
    op.drop_column("shopping_lists", "items")

    # Drop ingredients JSON column from recipes (replaced by recipe_ingredients)
    op.drop_column("recipes", "ingredients")

    # Drop brand_preferences table (replaced by ingredients)
    op.drop_table("brand_preferences")

    # Drop the brandconfidence enum type
    op.execute("DROP TYPE IF EXISTS brandconfidence")


def downgrade() -> None:
    # Recreate brand_preferences
    op.create_table(
        "brand_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("generic_item", sa.String(length=255), nullable=False),
        sa.Column("preferred_brand", sa.String(length=255), nullable=False),
        sa.Column("kroger_product_id", sa.String(length=100), nullable=True),
        sa.Column(
            "confidence",
            sa.Enum("CONFIRMED", "INFERRED", name="brandconfidence"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generic_item"),
    )

    # Restore JSON columns
    op.add_column("recipes", sa.Column("ingredients", sa.JSON(), nullable=True))
    op.add_column("shopping_lists", sa.Column("items", sa.JSON(), nullable=False, server_default="[]"))

    # Drop title from recipe_notes
    op.drop_column("recipe_notes", "title")

    # Drop new tables
    op.drop_table("kroger_tokens")
    op.drop_table("event_log")
    op.drop_table("shopping_list_items")
    op.drop_table("recipe_ingredients")
    op.drop_table("ingredients")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS actiontype")
