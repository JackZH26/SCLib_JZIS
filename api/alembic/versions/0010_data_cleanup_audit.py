"""One-shot cleanup of known-anomalous materials + source papers.

Revision ID: 0010_data_cleanup_audit
Down revision: 0009_cleanup_impossible_ambient

Audit driven by the 2026-04 Tc record reference sheet. Five concrete
issues, one migration:

A) **Schön-fraud fulleride corpus (2001–2003)**
   Fourteen C60 / C60-solvent materials with Tc 52–175 K at claimed
   ambient pressure, all traceable to cond-mat/01xx–02xx preprints
   of the Jan Hendrik Schön Bell Labs fabrication episode. The
   originals were retracted by Nature / Science in 2002-09–2003-03.
   Real Cs3C60 record is 38 K (under pressure); no fulleride above
   ~40 K is physically credible.

   Fix: (i) mark the materials ``needs_review=TRUE`` so they drop
   off /timeline and /materials immediately; (ii) mark every arXiv
   paper that sourced one of those impossible records
   ``status='retracted'`` with an explanatory reason. The aggregator
   (sibling commit) now skips retracted papers, making the cleanup
   durable across re-runs.

B) **Carbon nanotube @ 162 K (arxiv:2603.15305)**
   NER hallucination — CNT superconductivity is a few K at best, and
   "carbon nanotube" isn't a heavy-fermion material either. Flag
   for review; the paper itself might be legitimate research
   unrelated to the claimed 162 K, so we don't retract it, just
   hide the material.

C) **MgB2 records with Tc > 42 K**
   MgB2 tc_max = 39 K is correct at the material level, but five
   individual records (45–79 K) are NER mis-extractions — almost
   certainly picked up from comparison figures or non-SC
   transitions in the source text. Strip those records. Re-ingest
   via NER would re-introduce them; fixing that permanently needs
   per-family record-level sanity in the aggregator (tagged P2 in
   the review, deferred).

D) **Hg-1223 ambient @ 164 K**
   One record claims 164 K at ambient pressure for Hg-1223. The
   real numbers are 135 K ambient (Schilling 1993), 151 K ambient
   after pressure-quench (Deng PNAS 2026), and 164 K under 31 GPa
   (Gao 1994). The NER confused the pressurised record with the
   ambient one. Strip the single bad record.

E) **Pb-doped BSCCO shorthand misclassified as 'conventional'**
   Three materials — Bi(Pb)-2212, Pb-doped (BSCCO), Pb-Bi2212 —
   ended up in family='conventional' because ``classify_family``'s
   cuprate rule required the literal 'o' in the formula string
   (shorthand names don't have it) while the fallback conventional
   rule grabbed them via the 'pb' regex. The sibling commit adds
   phase-label shorthand recognition; this migration backfills
   the three existing rows.
"""
from alembic import op


revision = "0010_data_cleanup_audit"
down_revision = "0009_cleanup_impossible_ambient"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- A. Schön-era fulleride materials ---------------------------------
    op.execute("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'fulleride_tc_implausible_schon_era'
        WHERE family = 'fulleride'
          AND tc_max IS NOT NULL
          AND tc_max > 45;
    """)

    # --- A. Retract source papers feeding the impossible fulleride claims --
    # Criterion: paper is cited as paper_id by a fulleride record with
    # tc_kelvin > 45. Papers that merely cite Schön without reproducing
    # the impossible numbers are NOT touched.
    op.execute("""
        UPDATE papers
        SET status = 'retracted',
            retraction_reason = (
                'Source of fulleride Tc claim above physical plausibility '
                '(>45 K at ambient pressure). Associated with the 2001-2002 '
                'Jan Hendrik Schön (Bell Labs) fabrication episode; originals '
                'retracted by Nature / Science in 2002-09 through 2003-03.'
            ),
            retraction_date = COALESCE(retraction_date, DATE '2002-09-26')
        WHERE id IN (
            SELECT DISTINCT r.value->>'paper_id'
            FROM materials m
            CROSS JOIN LATERAL jsonb_array_elements(m.records) r
            WHERE m.family = 'fulleride'
              AND jsonb_typeof(r.value->'tc_kelvin') = 'number'
              AND (r.value->>'tc_kelvin')::float > 45
              AND (r.value->>'paper_id') LIKE 'arxiv:cond-mat/0%'
        );
    """)

    # --- B. Carbon nanotube NER hallucination ------------------------------
    op.execute("""
        UPDATE materials
        SET needs_review = TRUE,
            review_reason = 'cnt_tc_ner_hallucination'
        WHERE id = 'mat:carbonnanotube';
    """)

    # --- C. Strip MgB2 records with Tc > 42 K ------------------------------
    op.execute("""
        UPDATE materials m
        SET records = COALESCE((
            SELECT jsonb_agg(r.value)
            FROM jsonb_array_elements(m.records) r
            WHERE NOT (
                jsonb_typeof(r.value->'tc_kelvin') = 'number'
                AND (r.value->>'tc_kelvin')::float > 42
            )
        ), '[]'::jsonb)
        WHERE m.id = 'mat:mgb2';
    """)

    # --- D. Strip Hg-1223 "ambient 164 K" record ---------------------------
    op.execute("""
        UPDATE materials m
        SET records = COALESCE((
            SELECT jsonb_agg(r.value)
            FROM jsonb_array_elements(m.records) r
            WHERE NOT (
                jsonb_typeof(r.value->'tc_kelvin') = 'number'
                AND (r.value->>'tc_kelvin')::float > 140
                AND (
                    (jsonb_typeof(r.value->'pressure_gpa') = 'number'
                     AND (r.value->>'pressure_gpa')::float = 0)
                    OR (r.value->>'ambient_sc') = 'true'
                )
            )
        ), '[]'::jsonb)
        WHERE m.id = 'mat:hgca2ba2cu3o8';
    """)

    # --- E. Reclassify Pb-BSCCO shorthand to cuprate -----------------------
    op.execute("""
        UPDATE materials
        SET family = 'cuprate'
        WHERE id IN (
            'mat:bi(pb)-2212',
            'mat:pb-doped(bscco)',
            'mat:pb-bi2212'
        );
    """)


def downgrade() -> None:
    # Best-effort reversal. We restore needs_review=FALSE and
    # revert family / paper-status changes, but we can NOT restore
    # the stripped records (the NER output is in
    # papers.materials_extracted and can be re-derived by running
    # the aggregator).
    op.execute("""
        UPDATE materials
        SET needs_review = FALSE, review_reason = NULL
        WHERE review_reason IN (
            'fulleride_tc_implausible_schon_era',
            'cnt_tc_ner_hallucination'
        );
    """)
    op.execute("""
        UPDATE papers
        SET status = 'published',
            retraction_reason = NULL,
            retraction_date = NULL
        WHERE retraction_reason LIKE '%Schön%';
    """)
    op.execute("""
        UPDATE materials
        SET family = 'conventional'
        WHERE id IN (
            'mat:bi(pb)-2212',
            'mat:pb-doped(bscco)',
            'mat:pb-bi2212'
        );
    """)
