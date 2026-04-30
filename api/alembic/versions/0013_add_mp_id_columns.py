"""Add Materials Project external-id columns to materials.

Revision ID: 0013_add_mp_id_columns
Down revision: 0012_flag_citation_conflation

Phase B of the SCLib_JZIS × Materials Project integration. Adds three
columns to ``materials`` so each row can carry a stable link to the
DFT side of the world:

- ``mp_id``            : the chosen primary MP id (``"mp-18926"`` etc.).
                         Used for the "View on Materials Project"
                         button and the future RAG context-injection
                         lookup. Indexed (partial, NOT NULL only) for
                         the rare reverse lookup mp-id → SCLib formula.
- ``mp_alternate_ids`` : full list of MP ids whose ``formula_pretty``
                         matched ours, sorted by ``energy_above_hull``
                         (lowest first). The "primary" mp_id is just
                         ``mp_alternate_ids[0]`` — keeping both lets
                         clients explore polymorphs without an extra
                         round-trip.
- ``mp_synced_at``     : when the sync script last touched this row.
                         NULL means "never tried"; an old timestamp
                         means "tried but no match — re-try on next
                         pass" if MP added the material since.

The column names are deliberately verbose (``mp_alternate_ids`` not
``mp_ids``) so the API surface reads cleanly without having to
explain the difference. Symmetric with the existing ``arxiv_id`` /
``arxiv_other_ids`` pattern on papers, so reviewers don't need to
re-learn a convention here.

Idempotent / forward-only data: no backfill in this migration. The
sync script (``scripts/sync_mp_ids.py``) is run separately and is
itself idempotent.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0013_add_mp_id_columns"
down_revision = "0012_flag_citation_conflation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "materials",
        sa.Column("mp_id", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "materials",
        sa.Column(
            "mp_alternate_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "materials",
        sa.Column(
            "mp_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Partial index — most rows will have NULL mp_id (no match in MP),
    # so we don't need to index those. The index is for the reverse
    # lookup "given a Materials Project id, what's the SCLib material?"
    # which the future jzis-sclib client will use.
    op.create_index(
        "idx_materials_mp_id",
        "materials",
        ["mp_id"],
        unique=False,
        postgresql_where=sa.text("mp_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_materials_mp_id", table_name="materials")
    op.drop_column("materials", "mp_synced_at")
    op.drop_column("materials", "mp_alternate_ids")
    op.drop_column("materials", "mp_id")
