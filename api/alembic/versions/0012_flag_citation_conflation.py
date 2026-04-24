"""Flag materials whose only source is a review-scale paper's citation list.

Revision ID: 0012_flag_citation_conflation
Down revision: 0011_reclassify_nims_family

The 2026-04-24 YLuH₁₂ investigation exposed a systemic NER bug: when
a paper's introduction or comparison section lists prior-work Tc
values like "CaLuH₁₂ (239 K @ 160 GPa), YLuH₁₂ (247 K @ 160 GPa)",
the NER attributes those citations to the citing paper. Single-source
high-Tc materials produced by review-scale papers are therefore
disproportionately "citation conflation" artefacts rather than real
primary results.

This migration is the short-term containment: flag the most likely
victims ``needs_review = TRUE`` so they drop off the default
materials / timeline views while the NER prompt gets fixed in a
later pass.

Criterion (conservative — err on unflagged):

1. arXiv-derived only (``id LIKE 'mat:%'``)
2. ``total_papers = 1`` — no corroboration from independent papers
3. ``tc_max > 80`` — focus on high-Tc where the error cost is largest
4. Source paper's ``materials_extracted`` contains ≥ 15 distinct
   formulas (review-scale extraction volume)
5. ``needs_review`` is currently FALSE

The paper 2604.17712 (YCaH_n high-pressure superhydrides) is the
direct motivation, but the rule catches any similar review paper.

A targeted second pass un-flags YCaH_* materials — the paper's title
explicitly studies ``YCaH_n (n = 8–20)``, so those are genuine primary
results and should NOT be hidden.
"""
from alembic import op


revision = "0012_flag_citation_conflation"
down_revision = "0011_reclassify_nims_family"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: flag citation-conflation candidates across the corpus.
    op.execute("""
        WITH review_papers AS (
            SELECT p.id AS paper_id
            FROM papers p
            WHERE jsonb_array_length(p.materials_extracted) >= 15
        )
        UPDATE materials m
        SET needs_review  = TRUE,
            review_reason = 'citation_conflation_review_paper'
        FROM review_papers rp
        WHERE m.id LIKE 'mat:%%'
          AND m.total_papers = 1
          AND m.tc_max > 80
          AND m.needs_review = FALSE
          AND rp.paper_id = (m.records->0->>'paper_id');
    """)

    # Step 2: un-flag the YCaH_n series (2604.17712's actual subject).
    # The paper studies n = 8–20; corresponding material ids are
    # mat:ycah8, mat:ycah12, etc. Anything we hit in step 1 from this
    # family is a legitimate primary result, not a citation.
    op.execute("""
        UPDATE materials
        SET needs_review  = FALSE,
            review_reason = NULL
        WHERE id LIKE 'mat:ycah%%'
          AND review_reason = 'citation_conflation_review_paper';
    """)


def downgrade() -> None:
    # Reverse exactly the rows we flagged (plus the YCaH un-flag
    # exception) — leave any other needs_review=TRUE row alone.
    op.execute("""
        UPDATE materials
        SET needs_review  = FALSE,
            review_reason = NULL
        WHERE review_reason = 'citation_conflation_review_paper';
    """)
