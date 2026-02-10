"""Add price and aliases to ingredients.

Revision ID: 003
Revises: 002
Create Date: 2026-02-10 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    # Add last_known_price column
    op.add_column(
        "ingredients",
        sa.Column("last_known_price", sa.Float(), nullable=True),
    )
    # Add aliases column (JSON array)
    op.add_column(
        "ingredients",
        sa.Column("aliases", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("ingredients", "aliases")
    op.drop_column("ingredients", "last_known_price")
