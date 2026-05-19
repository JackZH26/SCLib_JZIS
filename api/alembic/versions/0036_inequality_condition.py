"""Flag formulas carrying a glued-on inequality / range condition.

Revision ID: 0036_inequality_condition
Down revision: 0035_pipeline_state

``formula_validator._CONDITION_PATTERN`` caught ``(x = 0.3)`` style
conditions but missed inequality ranges NER sometimes appends
(``(1.78≤x≤1.88``, ``x>=0.1``). ``≤ ≥ < >`` never occur in a real
chemical formula, so any formula containing one is condition-bearing
prose, not a clean compound. The validator + the hourly
``_periodic_formula_audit`` now also match these; this migration is
the one-shot retrofit for rows already in the table.

``admin_decision`` rows are left untouched (human decisions are never
overridden). Tagged ``ner_extracted_descriptive_text`` to match the
bucket the periodic audit uses for condition matches, so the two
mechanisms never double-categorise the same row.

LOCKSTEP: the inequality alternation below is mirrored verbatim in
  ingestion/ingestion/extract/formula_validator.py::_CONDITION_PATTERN
  api/main.py::_FORMULA_CONDITION_REGEX
Keep all three identical when editing.
"""
from alembic import op


revision = "0036_inequality_condition"
down_revision = "0035_pipeline_state"
branch_labels = None
depends_on = None


# Only the NEW inequality part — the ``[xyzn]=[0-9]`` half was already
# retrofitted by earlier backfills, so scoping here keeps this
# migration's reverse precise.
_INEQUALITY_REGEX = r"[≤≥]|<=|>="


def upgrade() -> None:
    op.execute(f"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'ner_extracted_descriptive_text'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND formula ~ '{_INEQUALITY_REGEX}';
    """)


def downgrade() -> None:
    # Reverse exactly what this migration set: rows still wearing the
    # reason whose formula matches the inequality pattern. Scoped so it
    # cannot clobber flags set by 0020 / 0034's broader backfills.
    op.execute(f"""
        UPDATE materials
        SET needs_review = FALSE, review_reason = NULL
        WHERE review_reason = 'ner_extracted_descriptive_text'
          AND formula ~ '{_INEQUALITY_REGEX}';
    """)
