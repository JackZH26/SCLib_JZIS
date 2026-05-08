"""Flag the 4 Gemini-audit boundary categories (option A from review).

Revision ID: 0021_gemini_audit_flags
Down revision: 0020_strict_naming

The 2026-05-08 audit against Gemini's 4-category breakdown of
LLM-extraction errors found ~28 visible rows that fall into rules
the previous validators didn't catch. Per product decision (only
option A): hard-flag the boundary cases, don't touch the legitimate
parametric-stoichiometry (``(Ba1-xKx)Fe2As2``) or Greek-prefix
polymorph (``α-LaBH17``) families.

Categories flagged:

* ``english_element_name`` — Cat 1: ``Oxygen``, ``Sulfur`` and similar
  English chemistry words used as the formula. The blacklist
  expansion in formula_validator.py covers this; sibling commit
  also wires it into the validator and periodic audit.

* ``system_designator_not_compound`` — Cat 2B (~14 rows):
  ``Sr-Ru-O``, ``La-Ce-H``, ``Bi-Pb-Sr-Ca-Cu-O``. Element symbols
  separated by hyphens with no digits represent a compositional
  family / phase diagram, not a specific compound.

* ``phase_prefix_in_formula`` — Cat 3 (~5 rows): ``Fm-3m-CeH10``,
  ``P63/mmc-YMgH3``. Space-group symbol attached to formula —
  belongs in the ``space_group`` column instead.

* ``incomplete_or_charged_formula`` — Cat 4 (~6 rows):
  ``Al45-``, ``Al47-`` (charged clusters); ``YBa2Cu3O7-``,
  ``Bi2Sr2CaCu2O8+`` (oxygen-stoichiometry suffix lost during
  earlier cleanup).

Cat 2A (parametric stoich, ~579 rows) and Cat 3b (Greek polymorph
prefix, ~96 rows) deliberately NOT flagged — both are standard SC
literature notation.
"""
from alembic import op
from sqlalchemy import text


revision = "0021_gemini_audit_flags"
down_revision = "0020_strict_naming"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # The new English-element words are now in the existing
    # blacklist regex (sibling commit), so 0020's
    # 'ner_extracted_descriptive_text' rule already covers them on
    # the next periodic audit. Use a dedicated reason here so this
    # specific subset is audit-distinct.
    bind.execute(text(r"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'english_element_name'
        WHERE needs_review = FALSE
          AND formula ~* '\m(hydrogen|oxygen|nitrogen|sulfur|sulphur|fluorine|chlorine|bromine|iodine|silicon|water|hydride|hydrides|oxide|oxides|sulfide|sulfides|selenide|selenides|telluride|tellurides|arsenide|arsenides|phosphide|phosphides|nitride|nitrides|carbide|carbides|silicide|silicides|fluoride|chloride|bromide|iodide)\M';
    """))

    bind.execute(text(r"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'system_designator_not_compound'
        WHERE needs_review = FALSE
          AND formula ~ '^([A-Z][a-z]?-){2,}[A-Z][a-z]?$';
    """))

    bind.execute(text(r"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'phase_prefix_in_formula'
        WHERE needs_review = FALSE
          AND formula ~ '^(Fd-?3m|Fm-?3m|Im-?3m|Pm-?3m|Pnma|P6_?3?/?mmc?|P6/mmm|R-?3m|R-?3c|I4/mmm|I4/mcm|Pn-?3m|P6_?3mc|C2/m|Cmcm|P-?1|P21/c|P-43m|P4/nmm|Pm-3n)-';
    """))

    bind.execute(text(r"""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'incomplete_or_charged_formula'
        WHERE needs_review = FALSE
          AND formula ~ '[A-Za-z0-9][+\-]$';
    """))


def downgrade() -> None:
    op.execute("""
        UPDATE materials
        SET needs_review = FALSE, review_reason = NULL
        WHERE review_reason IN (
            'english_element_name',
            'system_designator_not_compound',
            'phase_prefix_in_formula',
            'incomplete_or_charged_formula'
        );
    """)
