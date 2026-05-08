"""Apply strict-naming rules to legacy materials.

Revision ID: 0020_strict_naming
Down revision: 0019_terminal_formula_cleanup

Two-pronged cleanup that mirrors
``ingestion/ingestion/extract/formula_validator.py``:

1. **Whitespace strip.** Chemical formulas never contain spaces;
   ``(La, Y )H10`` and ``Ba 2 Cu 3 O7`` are NER artefacts. ``UPDATE``
   on materials.formula and formula_normalized + the in-place rename
   pattern from 0018/0019 for any id whose stripped form differs.
   Also clean papers.materials_extracted so re-aggregation can't
   reintroduce them.

2. **Descriptive-text flag.** Rows whose formula contains an English
   descriptor (``interface``, ``bilayer``, ``doped``, ``compound``,
   …) are NER pulling sentence fragments. Flag ``needs_review=TRUE``
   with reason ``ner_extracted_descriptive_text`` so they drop off
   the default materials list. Same for rows starting with a digit /
   lowercase letter (formulas must lead with a capital element symbol
   or a bracket).

Going forward, the NER post-process + aggregator both run the same
validator before writing, so this is a one-shot retrofit. The
periodic audit task in api/main.py (sibling commit) re-runs the
flag predicate hourly to catch anything the validators miss.
"""
from alembic import op
from sqlalchemy import text


revision = "0020_strict_naming"
down_revision = "0019_terminal_formula_cleanup"
branch_labels = None
depends_on = None


# Mirrors ingestion/ingestion/extract/formula_validator.py::_BLACKLIST_PATTERN
# Keep in sync if either is edited. Word boundaries via the ``\m``/``\M``
# Postgres regex flags (POSIX equivalents of ``\b``).
_BLACKLIST_REGEX = (
    r"\m("
    r"interface|bilayer|trilayer|multilayer|monolayer|superlattice|"
    r"superlattices|homobilayer|homobilayers|heterostructure|graphene|"
    r"diamond|molecule|molecules|organic|compound|compounds|system|"
    r"systems|doped|undoped|intercalated|hybrid|twisted|valley|bulk|"
    r"ladder|mirror|surface|surfaces|nanoparticle|nanoparticles|film|"
    r"films|wire|wires|polycrystal|polycrystals|tube|tubes|composition|"
    r"compositions|underdoped|overdoped|optimal|optimally|holes?|"
    r"electrons?|cells?|samples?|layers?|chiral|kagome|nanotube|"
    r"nanotubes|nanowire|nanowires"
    r")\M"
)
_CONDITION_REGEX = r"\(?\s*[xyzn]\s*=\s*[0-9]"


def upgrade() -> None:
    bind = op.get_bind()

    # --- Step 1A: strip whitespace from materials.formula + normalized
    bind.execute(text(r"""
        UPDATE materials
        SET formula = REGEXP_REPLACE(formula, '\s+', '', 'g')
        WHERE formula ~ '\s';
    """))
    bind.execute(text(r"""
        UPDATE materials
        SET formula_normalized = REGEXP_REPLACE(formula_normalized, '\s+', '', 'g')
        WHERE formula_normalized ~ '\s';
    """))

    # --- Step 1B: strip whitespace inside records[].formula and
    #             papers.materials_extracted[].formula (defense-in-
    #             depth — aggregator re-reads materials_extracted).
    for table, col in [("materials", "records"),
                       ("papers", "materials_extracted")]:
        bind.execute(text(f"""
            UPDATE {table} t
            SET {col} = (
                SELECT jsonb_agg(
                    CASE
                      WHEN jsonb_typeof(r.value->'formula') = 'string'
                       AND (r.value->>'formula') ~ '\\s'
                      THEN jsonb_set(r.value, '{{formula}}', to_jsonb(
                            REGEXP_REPLACE(r.value->>'formula', '\\s+', '', 'g')
                      ))
                      ELSE r.value
                    END
                    ORDER BY ord
                )
                FROM jsonb_array_elements(t.{col}) WITH ORDINALITY AS r(value, ord)
            )
            WHERE t.{col}::text ~ '\\s';
        """))

    # --- Step 1C: rename material ids whose stripped form differs from
    #             the current id (eg ``mat:bafe1.886rh0.114as2`` is
    #             clean, but ids like ``mat:(la,y)h 10`` exist when
    #             whitespace leaked into the normalized key).
    bind.execute(text(r"""
        DO $do$
        DECLARE r RECORD; new_id TEXT;
        BEGIN
            FOR r IN SELECT id, records FROM materials
                     WHERE id ~ '\s' ORDER BY id LOOP
                new_id := REGEXP_REPLACE(r.id, '\s+', '', 'g');
                IF new_id = r.id THEN CONTINUE; END IF;
                IF EXISTS (SELECT 1 FROM materials WHERE id = new_id) THEN
                    UPDATE materials SET records = records || r.records
                    WHERE id = new_id;
                    DELETE FROM materials WHERE id = r.id;
                ELSE
                    UPDATE materials SET id = new_id WHERE id = r.id;
                END IF;
            END LOOP;
        END $do$;
    """))

    # --- Step 2: flag descriptive-text materials. Three predicates:
    #             blacklist word, condition descriptor, no-uppercase
    #             letter. Mark needs_review with a stable reason so
    #             admins can audit + bulk-unflag.
    bind.execute(text(f"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'ner_extracted_descriptive_text'
        WHERE needs_review = FALSE
          AND (
                formula ~* '{_BLACKLIST_REGEX}'
             OR formula ~  '{_CONDITION_REGEX}'
             OR formula !~ '[A-Z]'
          );
    """))


def downgrade() -> None:
    # Best-effort: clear the flag we set; whitespace stripping is
    # irreversible without the original strings.
    op.execute("""
        UPDATE materials
        SET needs_review = FALSE, review_reason = NULL
        WHERE review_reason = 'ner_extracted_descriptive_text';
    """)
