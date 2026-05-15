"""Add evidence-tier columns: dominant_evidence, tc_max_experimental, tc_max_theoretical.

Revision ID: 0029_evidence_tier
Down revision: 0028_rename_arxiv_drop_topo

P1b A2: Split tc_max into experimental vs theoretical tiers so users
can distinguish measured values from DFT predictions. The aggregator
populates these from the NER evidence_type field (expanded in B1 from
"primary"/"cited" to "primary_experimental"/"primary_theoretical"/"cited").
"""
import sqlalchemy as sa
from alembic import op

revision = "0029_evidence_tier"
down_revision = "0028_rename_arxiv_drop_topo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("materials", sa.Column("dominant_evidence", sa.String(20)))
    op.add_column("materials", sa.Column("tc_max_experimental", sa.Float()))
    op.add_column("materials", sa.Column("tc_max_theoretical", sa.Float()))


def downgrade() -> None:
    op.drop_column("materials", "tc_max_theoretical")
    op.drop_column("materials", "tc_max_experimental")
    op.drop_column("materials", "dominant_evidence")
