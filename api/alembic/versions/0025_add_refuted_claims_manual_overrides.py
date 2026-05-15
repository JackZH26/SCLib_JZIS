"""Add refuted_claims and manual_overrides tables.

Revision ID: 0025_refuted_overrides
Down revision: 0024_formula_tightening

Part of P0 pipeline optimization. Two new infrastructure tables:

1. **refuted_claims** — Materials whose SC claims have been scientifically
   refuted (LK-99, Dias retractions, AgB₂, ZrZn₂, etc.). The aggregator
   checks this table and auto-sets ``disputed=True`` on matching materials.

2. **manual_overrides** — Curated per-compound Tc corrections and upper-bound
   caps. Dual mode: exact replacement (``is_cap=False``) for P0 hotfixes,
   or ceiling clamp (``is_cap=True``) for physical upper bounds. These are
   never overwritten by automated re-aggregation.
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_refuted_overrides"
down_revision = "0024_formula_tightening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- refuted_claims ---
    op.create_table(
        "refuted_claims",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("formula", sa.String(200), nullable=False, index=True),
        sa.Column("canonical", sa.String(200), nullable=False, index=True),
        sa.Column(
            "claim_type", sa.String(50), nullable=False,
            comment="room_temp_sc | superconductor | tc_value",
        ),
        sa.Column("claimed_tc", sa.Float, nullable=True),
        sa.Column("refutation_doi", sa.String(200), nullable=True),
        sa.Column("refutation_year", sa.SmallInteger, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- manual_overrides ---
    op.create_table(
        "manual_overrides",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("formula", sa.String(200), nullable=False, index=True),
        sa.Column("canonical", sa.String(200), nullable=False, index=True),
        sa.Column(
            "field", sa.String(50), nullable=False,
            comment="target column: tc_max | tc_ambient | hc2_tesla | pairing_symmetry | ...",
        ),
        sa.Column(
            "override_value", sa.Text, nullable=False,
            comment="JSON-encoded value (number as string, or quoted string for enums)",
        ),
        sa.Column(
            "is_cap", sa.Boolean, nullable=False,
            server_default="false",
            comment="True = upper-bound clamp; False = exact replacement",
        ),
        sa.Column(
            "source", sa.String(200), nullable=False,
            comment="DOI, review reference, or free-text provenance",
        ),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "created_by", sa.String(100), nullable=False,
            server_default="system",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_overrides_canonical_field",
        "manual_overrides",
        ["canonical", "field"],
    )


def downgrade() -> None:
    op.drop_index("idx_overrides_canonical_field", table_name="manual_overrides")
    op.drop_table("manual_overrides")
    op.drop_table("refuted_claims")
