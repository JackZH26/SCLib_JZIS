"""Add ``needs_review`` flag to hide implausible/unvetted materials.

Revision ID: 0005_needs_review
Down revision: 0004_null_default_flags

Materials with aggregated Tc above 250 K at ambient pressure are
almost certainly NER extraction errors: the LLM routinely confuses
Curie temperatures of manganites (La₀·₆₇Sr₀·₃₃MnO₃ → 347 K), melting
points, or tensile/mechanical transitions with superconducting Tc.
Confirmed ambient-pressure SC Tc tops out at ~140 K (cuprates); even
high-pressure hydrides only reach ~250 K near 200 GPa, which would
show with a non-zero ``pressure_gpa``.

Rather than delete these rows (losing the audit trail), we flag them
``needs_review=true`` and the materials list endpoint filters them out
by default. The rows stay reachable by direct id for admin review;
setting ``?include_pending=true`` on GET /materials also surfaces them.

``review_reason`` carries a short machine-readable tag (e.g.
``tc_max_exceeds_250K``) so the frontend / admin UI can explain *why*
a row was held back.

Backfill sets both columns for all existing rows so the filter works
immediately after migration; the aggregator keeps them in sync on
every subsequent run.
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_needs_review"
down_revision = "0004_null_default_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "materials",
        sa.Column(
            "needs_review",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "materials",
        sa.Column("review_reason", sa.String(200), nullable=True),
    )

    # Backfill: flag any material whose reported max / ambient Tc
    # exceeds the physical sanity threshold.
    op.execute("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'tc_max_exceeds_250K'
        WHERE COALESCE(tc_max, 0) > 250
           OR COALESCE(tc_ambient, 0) > 250;
    """)

    # Index the flag so the common query (WHERE needs_review = FALSE)
    # can skip the flagged rows efficiently once we have millions of
    # materials. Partial index keeps it tiny — only the minority of
    # flagged rows end up in the index.
    op.create_index(
        "idx_materials_needs_review",
        "materials",
        ["needs_review"],
        postgresql_where=sa.text("needs_review = TRUE"),
    )


def downgrade() -> None:
    op.drop_index("idx_materials_needs_review", table_name="materials")
    op.drop_column("materials", "review_reason")
    op.drop_column("materials", "needs_review")
