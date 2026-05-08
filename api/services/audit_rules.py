"""Nightly data-audit rule registry.

Each rule is one ``AuditRule`` row with:

* ``name`` — also written into ``materials.review_reason`` so the
  admin queue groups by it.
* ``severity`` — ``critical`` rows are hidden from default views;
  ``warn``/``info`` are observed in audit_reports without flipping
  needs_review (use them for trend-watching).
* ``description`` — short human gloss surfaced in the admin UI.
* ``predicate`` — SQL fragment slotted into ``WHERE … AND (…)`` of
  the runner. Must reference ``materials`` columns directly; CTEs
  go in ``setup`` if the rule needs row-aware joins.
* ``setup`` — optional CTE prefix, joined via ``WITH`` before the
  UPDATE. Used by rules that need cross-table joins (citation
  conflation, retracted-source) so the predicate stays readable.

Two important guarantees the runner enforces:

1. **Idempotent.** A rule only flips ``needs_review`` from FALSE
   to TRUE. Re-running the same rule is a no-op once steady state
   is reached.
2. **Admin-override aware.** If
   ``materials.admin_decision->>'rule' = '<this rule>'`` an
   admin has already reviewed and signed off; the runner skips it
   so manual review work isn't undone the next night.

Rule names line up with the categories in the design proposal:
  A naming, B Tc, C pressure, D evidence, E year, F citation,
  G cross-field, H retraction. D and G land later — left here as
  empty stubs once the corpus has matured.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuditRule:
    name: str
    severity: str  # 'critical' | 'warn' | 'info'
    description: str
    predicate: str
    setup: str = ""  # optional CTE prefixed before the UPDATE


# Family-specific Tc ceilings. Anything above this is implausible at
# *any* pressure for that family. Source: 2026-04 reference sheet
# (see project memory).
_FAMILY_TC_CAPS = {
    "cuprate":       165.0,
    "iron_based":    110.0,
    "nickelate":      85.0,
    "hydride":       270.0,
    "mgb2":           42.0,
    "heavy_fermion":  25.0,
    "fulleride":      45.0,
    "conventional":   28.0,
}

# Build the SQL VALUES list for the join in the Tc-cap rule.
_TC_CAPS_SQL = ", ".join(
    f"('{f}', {cap})" for f, cap in _FAMILY_TC_CAPS.items()
)


# ============================================================
# Rule registry
# ============================================================

RULES: list[AuditRule] = [
    # --------------------------------------------------------
    # B. Tc temperature — physical-plausibility caps per family
    # --------------------------------------------------------
    AuditRule(
        name="tc_exceeds_family_cap",
        severity="critical",
        description=(
            "Aggregated tc_max above the family's known physical "
            "ceiling (any pressure)."
        ),
        setup=f"""
            WITH caps(family, cap) AS (
                VALUES {_TC_CAPS_SQL}
            )
        """,
        predicate="""
            EXISTS (
                SELECT 1 FROM caps
                WHERE caps.family = materials.family
                  AND materials.tc_max > caps.cap
            )
        """,
    ),
    AuditRule(
        name="tc_at_ambient_above_record",
        severity="critical",
        description=(
            "ambient_sc=true but tc_max above the documented ambient "
            "record (Hg-1223 quench, 152 K, Deng PNAS 2026)."
        ),
        predicate="ambient_sc = TRUE AND tc_max > 152",
    ),

    # --------------------------------------------------------
    # C. Pressure
    # --------------------------------------------------------
    AuditRule(
        name="implausible_pressure",
        severity="critical",
        description=(
            "Any record with pressure_gpa < 0 or > 500."
        ),
        predicate="""
            EXISTS (
                SELECT 1 FROM jsonb_array_elements(materials.records) r
                WHERE jsonb_typeof(r.value->'pressure_gpa') = 'number'
                  AND ((r.value->>'pressure_gpa')::float < 0
                    OR (r.value->>'pressure_gpa')::float > 500)
            )
        """,
    ),
    AuditRule(
        name="hydride_low_pressure_high_tc",
        severity="critical",
        description=(
            "Hydride material with a record claiming Tc > 100 K and "
            "pressure < 50 GPa (ambient hydride SC tops at ~10 K)."
        ),
        predicate="""
            family = 'hydride'
            AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(materials.records) r
                WHERE jsonb_typeof(r.value->'tc_kelvin') = 'number'
                  AND (r.value->>'tc_kelvin')::float > 100
                  AND jsonb_typeof(r.value->'pressure_gpa') = 'number'
                  AND (r.value->>'pressure_gpa')::float < 50
            )
        """,
    ),
    AuditRule(
        name="ambient_sc_with_high_pressure",
        severity="critical",
        description=(
            "ambient_sc=true on a record but pressure_gpa > 1 — "
            "self-contradictory."
        ),
        predicate="""
            EXISTS (
                SELECT 1 FROM jsonb_array_elements(materials.records) r
                WHERE (r.value->>'ambient_sc') = 'true'
                  AND jsonb_typeof(r.value->'pressure_gpa') = 'number'
                  AND (r.value->>'pressure_gpa')::float > 1
            )
        """,
    ),

    # --------------------------------------------------------
    # E. Year sanity
    # --------------------------------------------------------
    AuditRule(
        name="record_year_out_of_range",
        severity="warn",
        description=(
            "Record year outside [1980, current_year + 1] — likely a "
            "parse error."
        ),
        predicate="""
            EXISTS (
                SELECT 1 FROM jsonb_array_elements(materials.records) r
                WHERE jsonb_typeof(r.value->'year') = 'number'
                  AND ((r.value->>'year')::int < 1980
                    OR (r.value->>'year')::int >
                       EXTRACT(YEAR FROM NOW())::int + 1)
            )
        """,
    ),
    AuditRule(
        name="discovery_year_mismatch",
        severity="info",
        description=(
            "discovery_year more than 5 years before the earliest "
            "record year — usually NER putting a citation date in "
            "discovery_year."
        ),
        predicate="""
            discovery_year IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(materials.records) r
                WHERE jsonb_typeof(r.value->'year') = 'number'
                  AND (r.value->>'year')::int - 5 > materials.discovery_year
            )
        """,
    ),

    # --------------------------------------------------------
    # F. Citation conflation (periodic re-check of one-shot 0012)
    # --------------------------------------------------------
    AuditRule(
        name="citation_conflation_review_paper",
        severity="critical",
        description=(
            "Single-source high-Tc material whose only paper extracted "
            "≥ 15 distinct formulas (review-scale paper). NER probably "
            "attributed a cited Tc to the citing paper."
        ),
        setup="""
            WITH review_papers AS (
                SELECT id FROM papers
                WHERE jsonb_array_length(materials_extracted) >= 15
            )
        """,
        predicate="""
            id LIKE 'mat:%%'
            AND total_papers = 1
            AND tc_max > 80
            AND (records->0->>'paper_id') IN (SELECT id FROM review_papers)
        """,
    ),

    # --------------------------------------------------------
    # G. Cross-field consistency
    # --------------------------------------------------------
    AuditRule(
        name="family_unconv_contradiction",
        severity="critical",
        description=(
            "is_unconventional=TRUE but family='conventional'."
        ),
        predicate=(
            "is_unconventional = TRUE AND family = 'conventional'"
        ),
    ),

    # --------------------------------------------------------
    # H. Retracted-source contagion
    # --------------------------------------------------------
    AuditRule(
        name="sole_source_retracted",
        severity="critical",
        description=(
            "All source papers of this material are retracted "
            "(papers.status='retracted')."
        ),
        setup="""
            WITH per_mat AS (
                SELECT m.id AS mat_id,
                       COUNT(*) AS n_records,
                       COUNT(*) FILTER (
                           WHERE p.status = 'retracted'
                       ) AS n_retracted
                FROM materials m
                CROSS JOIN LATERAL jsonb_array_elements(m.records) AS r
                LEFT JOIN papers p ON p.id = (r.value->>'paper_id')
                WHERE jsonb_typeof(r.value->'paper_id') = 'string'
                GROUP BY m.id
            )
        """,
        predicate="""
            id IN (
                SELECT mat_id FROM per_mat
                WHERE n_records > 0 AND n_records = n_retracted
            )
        """,
    ),
]


def rule_by_name(name: str) -> AuditRule | None:
    """Lookup helper — handy for the admin override path that needs
    to know a rule's severity before deciding what to do."""
    for r in RULES:
        if r.name == name:
            return r
    return None
