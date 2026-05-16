"""Add best_credibility_tier to materials.

Revision ID: 0033_mat_best_cred_tier
Revises: 0032_paper_credibility_tier
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_mat_best_cred_tier"
down_revision = "0032_paper_credibility_tier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "materials",
        sa.Column("best_credibility_tier", sa.String(2), nullable=True),
    )
    op.create_index(
        "idx_materials_best_tier",
        "materials",
        ["best_credibility_tier"],
    )


def downgrade() -> None:
    op.drop_index("idx_materials_best_tier", table_name="materials")
    op.drop_column("materials", "best_credibility_tier")
