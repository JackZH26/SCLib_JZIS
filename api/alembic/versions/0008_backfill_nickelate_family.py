"""Backfill existing materials into the new 'nickelate' family.

Revision ID: 0008_backfill_nickelate_family
Down revision: 0007_ask_history_bookmarks

Before this revision, ``classify_family()`` recognized cuprate /
iron_based / hydride / mgb2 / heavy_fermion / fulleride /
conventional. Nickelate oxides — infinite-layer NdNiO₂ (Li et al.
2019), Ruddlesden-Popper La₃Ni₂O₇ (Sun et al. 2023, ≈80 K under
pressure), and the growing 2024+ cohort — fell through every rule
and landed with ``family = NULL``, rendering as "Other" on the
timeline and search family filter.

The aggregator now returns ``'nickelate'`` for formulas containing
Ni + O but neither Cu nor Fe. This migration applies the same rule
to historical rows so the corpus reflects the new taxonomy
immediately — no manual re-ingest needed.

The match uses case-sensitive LIKE against the original ``formula``
column (not the lowercased ``formula_normalized``) because element
symbols are unambiguous only in their native case ("Ni" is nickel;
"ni" could be a substring of anything). The rule is the DB
equivalent of the Python ``elements`` check: contains "Ni", contains
"O", excludes "Cu" and "Fe".
"""
from alembic import op


revision = "0008_backfill_nickelate_family"
down_revision = "0007_ask_history_bookmarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE materials
        SET family = 'nickelate'
        WHERE family IS NULL
          AND formula LIKE '%Ni%'
          AND formula LIKE '%O%'
          AND formula NOT LIKE '%Cu%'
          AND formula NOT LIKE '%Fe%';
    """)


def downgrade() -> None:
    # Reversible: drop the family flag back to NULL. We deliberately
    # only null out rows we set in this migration; a human who later
    # curated ``family = 'nickelate'`` by hand would keep theirs.
    op.execute("""
        UPDATE materials
        SET family = NULL
        WHERE family = 'nickelate'
          AND formula LIKE '%Ni%'
          AND formula LIKE '%O%'
          AND formula NOT LIKE '%Cu%'
          AND formula NOT LIKE '%Fe%';
    """)
