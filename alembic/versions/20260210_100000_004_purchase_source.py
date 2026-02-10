"""Add purchase_source to ingredients.

Revision ID: 004
Revises: 003
Create Date: 2026-02-10 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    # Add purchase_source column for non-Kroger items
    # Values: null (default = Kroger), "sprouts", "liquor_store", "other"
    op.add_column(
        "ingredients",
        sa.Column("purchase_source", sa.String(50), nullable=True),
    )


def downgrade():
    op.drop_column("ingredients", "purchase_source")
