"""Drop ``server_default='false'`` on boolean flags that should be tri-state.

Revision ID: 0004_null_default_flags
Down revision: 0003_unified_auth

Migration 0002 gave ``is_topological``, ``has_competing_order`` and
``is_2d_or_interface`` a ``server_default='false'``. NIMS CSV imports
don't explicitly set these, so every imported row ended up flagged
"confirmed non-topological" / "confirmed single-order", regardless of
whether the underlying literature actually supported that claim.

The aggregator's weighted-boolean logic (see
``materials_aggregator._weighted_boolean``) expects NULL == "unknown"
semantics, so we drop the default here. Existing NIMS-origin rows are
backfilled to NULL so they match the new semantics immediately; rows
that have NER-backed evidence (from the aggregator) keep their
weighted-voting verdict.

``disputed`` is left at server_default=false — a material is innocent
(non-disputed) until proven otherwise, and a NULL there would force us
to thread four-way logic through every filter UI. Aggregator promotes
it to True when numeric Tc spread > 30% or NER asserts disputed=true.
"""
from alembic import op


revision = "0004_null_default_flags"
down_revision = "0003_unified_auth"
branch_labels = None
depends_on = None


_FLAGS = ["is_topological", "has_competing_order", "is_2d_or_interface"]


def upgrade() -> None:
    for col in _FLAGS:
        op.alter_column("materials", col, server_default=None)
        # Backfill NIMS rows: without NER evidence they're truly
        # unknown, so downgrade the default "false" to NULL. Rows the
        # aggregator has touched (id LIKE 'mat:%') already carry the
        # right value and we leave them alone.
        op.execute(
            f"UPDATE materials SET {col} = NULL "
            f"WHERE id LIKE 'nims:%' AND {col} = FALSE;"
        )


def downgrade() -> None:
    for col in _FLAGS:
        # Restore the bad default for symmetry; re-backfilling false on
        # downgrade is intentional so a downgrade + re-upgrade cycle
        # ends up in the same state.
        op.execute(f"UPDATE materials SET {col} = FALSE WHERE {col} IS NULL;")
        op.alter_column("materials", col, server_default="false")
