"""Final brute-force strip of $/_/{/} markup from all materials.

Revision ID: 0017_final_strip_all_markup
Down revision: 0016_strip_unpaired_dollars

After 0014 / 0015 / 0016, a post-cleanup audit on prod still found
3227 materials with ``$``, ``_``, ``{`` or ``}`` in the formula
column — example ``CsV_3Sb_5-xSn_x``. The earlier Python-loop
migrations got tripped up somewhere (race during crash-loop, regex
edge case, or a code path that simply never visited those rows).

This migration ditches Python and uses a single chained Postgres
REPLACE per column. Trivially safe: REPLACE is deterministic, the
chars we strip have no chemical-meaning role in a formula display
string, and we limit the WHERE clause to rows that actually need
cleaning so the write set stays small.

We deliberately do NOT touch ``id`` — UPDATEing the primary key
risks duplicate-key conflicts (576 dirty ids would need the same
race-aware loop the previous migrations bungled). Display strings
are what users see; ids can be left for a future targeted pass.
"""
from alembic import op
from sqlalchemy import text


revision = "0017_final_strip_all_markup"
down_revision = "0016_strip_unpaired_dollars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # formula — what the UI shows in tooltips, badges, the materials
    # list. No chemical meaning is lost by stripping these chars.
    bind.execute(text(r"""
        UPDATE materials
        SET formula = REPLACE(REPLACE(REPLACE(REPLACE(formula,
            '$', ''), '_', ''), '{', ''), '}', '')
        WHERE formula ~ '[$_{}]';
    """))

    # formula_normalized — internal grouping key. Cleaning it just
    # tightens the merge condition for future aggregator runs.
    bind.execute(text(r"""
        UPDATE materials
        SET formula_normalized = REPLACE(REPLACE(REPLACE(REPLACE(
            formula_normalized,
            '$', ''), '_', ''), '{', ''), '}', '')
        WHERE formula_normalized ~ '[$_{}]';
    """))


def downgrade() -> None:
    pass
