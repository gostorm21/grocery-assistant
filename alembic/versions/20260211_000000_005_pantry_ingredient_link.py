"""Link pantry_items to ingredients.

Revision ID: 005
Revises: 004
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    # Add ingredient_id to pantry_items for linking
    op.add_column(
        "pantry_items",
        sa.Column("ingredient_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_pantry_items_ingredient_id",
        "pantry_items",
        "ingredients",
        ["ingredient_id"],
        ["id"],
    )


def downgrade():
    # Remove foreign key and column
    op.drop_constraint("fk_pantry_items_ingredient_id", "pantry_items", type_="foreignkey")
    op.drop_column("pantry_items", "ingredient_id")
