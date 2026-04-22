"""Null out ``pressure_gpa = 0`` on records whose Tc is physically
impossible at ambient pressure for their family.

Revision ID: 0009_cleanup_impossible_ambient
Down revision: 0008_backfill_nickelate_family

Background
----------

The historical NER prompt said "pressure_gpa: 0.0 if ambient, null if
not stated". In practice the LLM almost never emitted null — it
defaulted to 0.0 whenever the paper didn't mention pressure, even for
high-pressure hydride papers. A cross-tab on 2026-04-22 showed
~96% of records with pressure_gpa = 0 — clearly dominated by the
default, not real ambient measurements.

Fixing the prompt (see material_ner.py, same commit wave) prevents
future pollution, but the existing corpus still contains thousands
of records claiming "ambient superconductivity" when the paper
probably didn't mention pressure at all.

Strategy
--------

Rather than null every 0.0 (which would drop thousands of legitimate
cuprate / MgB₂ ambient measurements), apply family-specific
physical-plausibility caps. A record with pressure_gpa = 0 AND
tc_kelvin above the family's known-ambient ceiling is almost
certainly an error — either the pressure was not stated, or the Tc
itself is a hallucination. In either case, dropping the
pressure_gpa key is the conservative fix: the timeline will render
the dot as "ambient (unstated)" rather than confidently asserting
0 GPa.

Caps picked conservatively (prefer false negatives):

    cuprate       140 K   Hg-1223 record is ~134 K; above 140 at P=0
                          is either wrong or needs a citation.
    iron_based     60 K   FeSe/STO monolayers ~80 K exist but bulk
                          is ≤55 K; 60 K is a middle-ground threshold.
    nickelate      20 K   Infinite-layer thin films max ~15 K at
                          ambient; bulk RP nickelates need pressure.
    mgb2           42 K   MgB₂ record is 39 K; above 42 is nonsense.
    heavy_fermion  40 K   Heavy-fermion SC tops around UBe13 at 1 K,
                          URu2Si2 at 1.5 K, UTe2 at 2 K, PuCoGa5 at
                          18 K. 40 K is generous.
    fulleride      42 K   Cs3C60 is ~40 K (under pressure). Ambient
                          fullerides are lower.
    conventional   25 K   Nb3Ge sits at ~23 K, the conventional
                          record.
    hydride        15 K   Ambient hydride SC is a few K (MgH2).
                          Above 15 K at P=0 is definitely wrong.

The key is REMOVED (``record - 'pressure_gpa'``) rather than set to
null, to match the shape the new NER prompt emits ("omit when
unstated"). The timeline router treats a missing key the same as a
null value.

Downgrade intentionally does nothing — re-introducing the 0.0 would
re-pollute the corpus and the original value is unrecoverable
anyway.
"""
from alembic import op


revision = "0009_cleanup_impossible_ambient"
down_revision = "0008_backfill_nickelate_family"
branch_labels = None
depends_on = None


# Must be kept in sync with the doc above. Everything not listed
# (e.g. family IS NULL) is left alone — we only act where we have
# a principled family cap.
_AMBIENT_TC_CAPS_SQL = """(
    VALUES
      ('cuprate',       140.0),
      ('iron_based',     60.0),
      ('nickelate',      20.0),
      ('mgb2',           42.0),
      ('heavy_fermion',  40.0),
      ('fulleride',      42.0),
      ('conventional',   25.0),
      ('hydride',        15.0)
  ) AS caps(family, cap)
"""


def upgrade() -> None:
    # For every material whose family has a cap, re-emit the records
    # array with pressure_gpa stripped on offending entries. Use
    # jsonb_typeof to guard the numeric cast so a non-number
    # pressure_gpa (string, bool) doesn't crash the migration.
    op.execute(f"""
        UPDATE materials m
        SET records = (
            SELECT jsonb_agg(
                CASE
                  WHEN jsonb_typeof(r.value->'pressure_gpa') = 'number'
                   AND (r.value->>'pressure_gpa')::float = 0
                   AND jsonb_typeof(r.value->'tc_kelvin') = 'number'
                   AND (r.value->>'tc_kelvin')::float > caps.cap
                  THEN r.value - 'pressure_gpa'
                  ELSE r.value
                END
            )
            FROM jsonb_array_elements(m.records) r
        )
        FROM {_AMBIENT_TC_CAPS_SQL}
        WHERE m.family = caps.family
          AND EXISTS (
            SELECT 1
            FROM jsonb_array_elements(m.records) rr
            WHERE jsonb_typeof(rr.value->'pressure_gpa') = 'number'
              AND (rr.value->>'pressure_gpa')::float = 0
              AND jsonb_typeof(rr.value->'tc_kelvin') = 'number'
              AND (rr.value->>'tc_kelvin')::float > caps.cap
          );
    """)


def downgrade() -> None:
    # The original pressure_gpa=0 was pollution, not signal — putting
    # it back would undo a real improvement. Keep downgrade a no-op.
    pass
