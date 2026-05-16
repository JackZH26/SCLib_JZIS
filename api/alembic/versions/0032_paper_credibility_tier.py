"""Add credibility_tier and paper_type columns to papers.

Revision ID: 0032_paper_credibility_tier
Down revision: 0031_parent_variant_interface

Paper credibility scoring infrastructure:
- credibility_tier: T1 (highest) through T5 (lowest)
- paper_type: experimental / theoretical / computational / review
  (was only in NER JSONB, now a first-class column for fast queries)
"""
import sqlalchemy as sa
from alembic import op

revision = "0032_paper_credibility_tier"
down_revision = "0031_parent_variant_interface"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "papers",
        sa.Column("credibility_tier", sa.String(2), nullable=True,
                  comment="T1-T5: T1=highest credibility, T5=retracted/refuted"),
    )
    op.add_column(
        "papers",
        sa.Column("paper_type", sa.String(20), nullable=True,
                  comment="experimental|theoretical|computational|review"),
    )
    # Index for filtering by tier in aggregator queries
    op.create_index("idx_papers_credibility", "papers", ["credibility_tier"])


def downgrade() -> None:
    op.drop_index("idx_papers_credibility")
    op.drop_column("papers", "paper_type")
    op.drop_column("papers", "credibility_tier")
