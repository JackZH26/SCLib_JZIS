"""Rename discovery_year → arxiv_year; drop is_topological + is_2d_or_interface.

Revision ID: 0028_rename_arxiv_drop_topo
Down revision: 0027_widen_tc_float8

A1: The column was misleadingly named "discovery_year" — it actually
    stores the year the material first appeared in an arXiv paper, not
    when it was physically discovered. Renaming to "arxiv_year" aligns
    the schema with the data source (arXiv OAI-PMH) and the column's
    actual semantics.

A3: is_topological and is_2d_or_interface were NER-extracted boolean
    flags with an 87%+ null rate and <2% true rate. Review rounds showed
    they were unreliable (LLM guessing) and not useful for filtering.
    Decision D-5 locks their removal.
"""
import sqlalchemy as sa
from alembic import op

revision = "0028_rename_arxiv_drop_topo"
down_revision = "0027_widen_tc_float8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A1: rename discovery_year → arxiv_year
    op.alter_column("materials", "discovery_year", new_column_name="arxiv_year")
    # A3: drop unreliable NER-only boolean flags
    op.drop_column("materials", "is_topological")
    op.drop_column("materials", "is_2d_or_interface")


def downgrade() -> None:
    op.add_column(
        "materials",
        sa.Column("is_2d_or_interface", sa.Boolean(), server_default="false"),
    )
    op.add_column(
        "materials",
        sa.Column("is_topological", sa.Boolean(), server_default="false"),
    )
    op.alter_column("materials", "arxiv_year", new_column_name="discovery_year")
