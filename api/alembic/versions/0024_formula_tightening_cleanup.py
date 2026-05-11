"""Flag materials failing the 2026-05-11 tightened formula validator.

Revision ID: 0024_formula_tightening
Down revision: 0023_reviewer_role

Applies five NEW rejection categories that complement the original
0020 strict-naming pass:

1. **Literal placeholders** — "None", "unknown", "N/A", etc.
2. **Single bare element symbols** — "H", "C", "V", "S" etc. (too
   ambiguous for a material entry).
3. **Trade names / lab jargon** — "HOPG", "Grafoil", "tBLG", etc.
4. **Generic family names** — "cuprates", "ironpnictides", etc.
5. **Concatenated prose** — 10+ consecutive lowercase letters
   ("Bernalbilayergraphene", "neutronsuperfluidity") that slipped
   past the original word-boundary blacklist because the words are
   mashed together without spaces.
6. **Expanded blacklist** — English element names (niobium, platinum,
   mercury ...) and more descriptive terms (rhombohedral, amorphous,
   epitaxial, superconductor ...) not covered in 0020.

All flagged rows get ``needs_review = TRUE`` with a specific
``review_reason`` so admins can audit by category. Rows that already
have ``admin_decision`` set (manually reviewed) are skipped.
"""
from alembic import op
from sqlalchemy import text


revision = "0024_formula_tightening"
down_revision = "0023_reviewer_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. Literal placeholders ---
    bind.execute(text("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'literal_placeholder'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND LOWER(formula) IN ('none', 'unknown', 'n/a', 'na', 'null', 'tbd', '-', '?', '??');
    """))

    # --- 2. Single bare element symbol (one uppercase letter) ---
    bind.execute(text("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'single_element_symbol'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND formula ~ '^[A-Z]$';
    """))

    # --- 3. Trade names / lab jargon ---
    bind.execute(text("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'trade_name_not_compound'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND LOWER(formula) IN (
            'hopg', 'grafoil', 'papyex', 'grokene', 'swntrope', 'fgg',
            'swnt', 'swcnt', 'mwnt', 'mwcnt', 'dwnt', 'dwcnt', 'cnt',
            'tblg', 'blg', 'mlg', 'slg', '3dti', '2deg'
          );
    """))

    # --- 4. Generic family names ---
    bind.execute(text("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'generic_family_name'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND formula ~* '^(cuprates?|iron-?pnictides?|copper-?oxides?|pnictides?|chalcogenides?|borocarbides?|heavy-?fermions?|cuprate-?superconductors?|high-?tc-?cuprate(material)?s?|feas-?based-?materials?|214systems?)$';
    """))

    # --- 5. Concatenated prose (10+ consecutive lowercase) ---
    # Only flag if NOT already caught by the original 0020 pass
    # (those have review_reason = 'ner_extracted_descriptive_text').
    bind.execute(text("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'concatenated_prose'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND formula ~ '[a-z]{10,}';
    """))

    # --- 6. Expanded blacklist — English element + descriptor names ---
    # These are words NOT covered in the 0020 migration's regex.
    # Uses Postgres POSIX word boundaries (\m ... \M).
    bind.execute(text(r"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'descriptive_word_expanded'
        WHERE needs_review = FALSE
          AND admin_decision IS NULL
          AND formula ~* '\m(rhombohedral|borophene|phosphorene|silicene|stanene|germanene|amorphous|granular|polycrystalline|epitaxial|superconductors?|superfluidity|superfluid|quasicrystals?|proximitized|eutectic|graphite|niobium|platinum|gallium|vanadium|tantalum|lithium|zinc|aluminum|aluminium|lead|thallium|indium|bismuth|calcium|strontium|barium|lanthanum|cerium|uranium|thorium|plutonium|iron|cobalt|nickel|copper|manganese|chromium|titanium|molybdenum|tungsten|palladium|beryllium|magnesium|cadmium|zirconium|hafnium|rhodium|ruthenium|iridium|osmium|rhenium|technetium|gold|silver|boron|carbon|helium|neon|argon|krypton|xenon|phosphorus|antimony|arsenic|germanium|selenium|tellurium|potassium|sodium|rubidium|cesium|caesium|mercury)\M';
    """))


def downgrade() -> None:
    reasons = (
        "'literal_placeholder', 'single_element_symbol', "
        "'trade_name_not_compound', 'generic_family_name', "
        "'concatenated_prose', 'descriptive_word_expanded'"
    )
    op.execute(f"""
        UPDATE materials
        SET needs_review = FALSE, review_reason = NULL
        WHERE review_reason IN ({reasons});
    """)
