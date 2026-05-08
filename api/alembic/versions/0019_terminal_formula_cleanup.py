"""Terminal LaTeX cleanup — clean papers.materials_extracted too.

Revision ID: 0019_terminal_formula_cleanup
Down revision: 0018_clean_material_ids

Audit after 0018 found materials.formula re-polluted: 3322 dirty
rows where 0017 had cleaned 0. The crash culprit was the
ingest-daily cron firing between deploys — it harvests new arXiv
papers, runs the (then-still-loose) NER prompt, and aggregates
LaTeX-laden formulas into materials. Migration 0017 cleaned only
``materials.*``; ``papers.materials_extracted`` retained the dirty
NER output, so any later aggregator run re-emitted those values.

This migration closes the loop. Five steps in one transaction:

1. ``materials.formula`` — brute REGEXP_REPLACE strip.
2. ``materials.formula_normalized`` — same.
3. ``materials.records[].formula`` — JSONB rebuild via jsonb_set
   per element, so historical evidence rows render cleanly even
   when the user expands a material's per-paper trail.
4. ``papers.materials_extracted[].formula`` — same JSONB rebuild.
   This is the *source* the aggregator reads from; without
   cleaning it, every future aggregator pass would re-introduce
   dirty data regardless of how many follow-up cleanups we ship.
5. ``materials.id`` — rename DO-block from 0018 plus bookmark
   re-target. Catches the ~34 fresh dirty ids that landed between
   0017 and 0018.

Sibling commit 193555d already strengthened the NER prompt so
future LLM output starts clean, but the legacy ``materials_extracted``
records keep the old dirty strings until the next NER re-run. This
migration retroactively cleans them so the aggregator can keep
running on existing data without regressing.
"""
from alembic import op
from sqlalchemy import text


revision = "0019_terminal_formula_cleanup"
down_revision = "0018_clean_material_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. materials.formula
    bind.execute(text(r"""
        UPDATE materials
        SET formula = REGEXP_REPLACE(formula, '[$_{}]', '', 'g')
        WHERE formula ~ '[$_{}]';
    """))

    # 2. materials.formula_normalized
    bind.execute(text(r"""
        UPDATE materials
        SET formula_normalized = REGEXP_REPLACE(
            formula_normalized, '[$_{}]', '', 'g'
        )
        WHERE formula_normalized ~ '[$_{}]';
    """))

    # 3. materials.records[].formula — rebuild JSONB array, clean
    #    each element's formula field. ``jsonb_set`` is path-safe
    #    so we don't accidentally drop sibling fields.
    bind.execute(text(r"""
        UPDATE materials m
        SET records = (
            SELECT jsonb_agg(
                CASE
                  WHEN jsonb_typeof(r.value->'formula') = 'string'
                   AND (r.value->>'formula') ~ '[$_{}]'
                  THEN jsonb_set(r.value, '{formula}', to_jsonb(
                       REGEXP_REPLACE(r.value->>'formula', '[$_{}]', '', 'g')
                  ))
                  ELSE r.value
                END
                ORDER BY ord
            )
            FROM jsonb_array_elements(m.records) WITH ORDINALITY AS r(value, ord)
        )
        WHERE m.records::text ~ '[$_{}]';
    """))

    # 4. papers.materials_extracted[].formula — same JSONB rebuild,
    #    same idempotent semantics. The WHERE filter narrows to
    #    papers that actually carry NER output and any markup; the
    #    cost is one CASE eval per record but we don't pay it on
    #    the bulk of cuprate-only papers whose formulas are clean.
    bind.execute(text(r"""
        UPDATE papers p
        SET materials_extracted = (
            SELECT jsonb_agg(
                CASE
                  WHEN jsonb_typeof(m.value->'formula') = 'string'
                   AND (m.value->>'formula') ~ '[$_{}]'
                  THEN jsonb_set(m.value, '{formula}', to_jsonb(
                       REGEXP_REPLACE(m.value->>'formula', '[$_{}]', '', 'g')
                  ))
                  ELSE m.value
                END
                ORDER BY ord
            )
            FROM jsonb_array_elements(p.materials_extracted)
                  WITH ORDINALITY AS m(value, ord)
        )
        WHERE p.materials_extracted::text ~ '[$_{}]';
    """))

    # 5a. Drop user-twin duplicate bookmarks before re-target.
    bind.execute(text(r"""
        DELETE FROM bookmarks b1
        USING bookmarks b2
        WHERE b1.target_type = 'material'
          AND b1.target_id ~ '[$_{}]'
          AND b2.user_id = b1.user_id
          AND b2.target_type = 'material'
          AND b2.target_id = REGEXP_REPLACE(b1.target_id, '[$_{}]', '', 'g')
          AND b2.id != b1.id;
    """))

    # 5b. Re-target surviving bookmarks.
    bind.execute(text(r"""
        UPDATE bookmarks
        SET target_id = REGEXP_REPLACE(target_id, '[$_{}]', '', 'g')
        WHERE target_type = 'material'
          AND target_id ~ '[$_{}]';
    """))

    # 5c. Rename material ids — same DO-block as 0018.
    bind.execute(text(r"""
        DO $do$
        DECLARE
            r       RECORD;
            new_id  TEXT;
        BEGIN
            FOR r IN
                SELECT id, records
                FROM materials
                WHERE id ~ '[$_{}]'
                ORDER BY id
            LOOP
                new_id := REGEXP_REPLACE(r.id, '[$_{}]', '', 'g');
                IF new_id = r.id THEN CONTINUE; END IF;
                IF EXISTS (SELECT 1 FROM materials WHERE id = new_id) THEN
                    UPDATE materials
                    SET records = records || r.records
                    WHERE id = new_id;
                    DELETE FROM materials WHERE id = r.id;
                ELSE
                    UPDATE materials SET id = new_id WHERE id = r.id;
                END IF;
            END LOOP;
        END
        $do$;
    """))


def downgrade() -> None:
    pass
