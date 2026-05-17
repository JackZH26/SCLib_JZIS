"""Flag concatenated-descriptor formulas the boundary blacklist missed.

Revision ID: 0034_concat_descriptor
Down revision: 0033_mat_best_cred_tier

``formula_validator._BLACKLIST_PATTERN`` is word-boundary anchored
(``\\b...\\b``), so NER concatenations like ``TaNSmonolayer`` or
``Y-dopedBi2Sr2CaCu2O8`` slipped past it — no boundary exists between
the formula and the glued-on English descriptor. The validator now
also runs a boundary-less substring check (``_CONCAT_DESCRIPTOR``);
this migration is the one-shot retrofit for rows already in the table,
mirroring the new rule. ``admin_decision`` rows are left untouched so
human decisions are never overridden. The hourly
``_periodic_formula_audit`` in api/main.py applies the same predicate
going forward.

LOCKSTEP: the alternation below is mirrored verbatim in
  ingestion/ingestion/extract/formula_validator.py::_CONCAT_DESCRIPTOR
  api/main.py::_FORMULA_CONCAT_DESCRIPTOR_REGEX
Keep all three identical when editing.
"""
from alembic import op


revision = "0034_concat_descriptor"
down_revision = "0033_mat_best_cred_tier"
branch_labels = None
depends_on = None


_CONCAT_DESCRIPTOR_REGEX = (
    r"(monolayer|bilayer|trilayer|tetralayer|fewlayer|multilayer"
    r"|heterostructure|heterostructures|superlattice|superlattices"
    r"|nanotube|nanotubes|nanowire|nanowires|nanoparticle|nanoparticles"
    r"|nanosheet|nanosheets|nanoribbon|nanoribbons|nanostructure"
    r"|nanostructures|graphene|graphite|fullerene|thinfilm|epitaxial"
    r"|amorphous|polycrystalline|substrate|doped|undoped|intercalated)"
)


def upgrade() -> None:
    op.execute(f"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'ner_extracted_descriptive_text'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND formula ~* '{_CONCAT_DESCRIPTOR_REGEX}';
    """)


def downgrade() -> None:
    # Reverse exactly what this migration set: rows still wearing the
    # reason whose formula matches the concat pattern. Scoped so it
    # cannot clobber flags set by 0020's broader backfill.
    op.execute(f"""
        UPDATE materials
        SET needs_review = FALSE, review_reason = NULL
        WHERE review_reason = 'ner_extracted_descriptive_text'
          AND formula ~* '{_CONCAT_DESCRIPTOR_REGEX}';
    """)
