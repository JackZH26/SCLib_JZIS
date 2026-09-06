"""Nightly governance rules and the shared versioned anomaly-review policy.

Numeric findings retain raw values and require source-backed review. Thresholds
are operational references, not physical limits or replacement measurements.
Legacy governance rules remain distinct from scientific acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.anomaly_review import ANOMALY_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class AuditRule:
    name: str
    severity: str
    description: str
    predicate: str
    setup: str = ""
    suggested_fix: str = ""
    fix_query: str = ""


ANOMALY_RULE_NAME = f"scientific_anomaly_review:{ANOMALY_POLICY_VERSION}"
ANOMALY_RULE = AuditRule(
    name=ANOMALY_RULE_NAME,
    severity="critical",
    description="Versioned raw-preserving scientific anomaly review; no automatic acceptance.",
    predicate="FALSE",  # Evaluated by the canonical Python engine, never scalar SQL caps.
    suggested_fix=(
        "Inspect the retained source result and rule findings. Submit a source-linked "
        "revision proposal when warranted; never clip, delete or approve a measurement "
        "solely because of a threshold or a legacy override."
    ),
)

RULES: list[AuditRule] = [
    ANOMALY_RULE,
    AuditRule(
        name="arxiv_year_mismatch",
        severity="info",
        description=(
            "arxiv_year more than 5 years before the earliest "
            "record year — usually NER putting a citation date in "
            "arxiv_year."
        ),
        predicate="""
            arxiv_year IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(materials.records) r
                WHERE jsonb_typeof(r.value->'year') = 'number'
                  AND (r.value->>'year')::int - 5 > materials.arxiv_year
            )
        """,
        suggested_fix=(
            "Check publication and measurement dates against their source. "
            "Do not replace one kind of date with another or overwrite raw evidence."
        ),
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
        suggested_fix=(
            "Review cited versus original source attribution and retain the raw "
            "claim and locator. A review-paper heuristic is not proof of an error."
        ),
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
        suggested_fix=(
            "Set is_unconventional=false (if genuinely BCS), or "
            "reclassify the family to the correct unconventional type."
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
        suggested_fix=(
            "Set disputed=true. All supporting papers are retracted "
            "so the material's claims are unreliable."
        ),
        fix_query="""
            SELECT id, 'disputed',
                   COALESCE(disputed::text, 'false'),
                   'true'
            FROM materials
            WHERE review_reason = 'sole_source_retracted'
            LIMIT 10
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
