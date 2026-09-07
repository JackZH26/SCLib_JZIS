"""Roll per-paper NER records up into the ``materials`` table.

The arXiv pipeline writes ``papers.materials_extracted`` on every
upsert — that's the v2 NER output from ``material_ner.extract_materials``
for that one paper. This module sweeps all papers, groups the records
by *canonical* formula (so ``Bi_2Sr_2CaCu_2O_{8+δ}`` and ``Bi2Sr2CaCu2O8+d``
land in the same bucket), and upserts one row per canonical formula
into the ``materials`` table.

Key design choices, in order of how much they affect visible data:

1. **Formula canonicalization** — drops LaTeX syntax, normalizes
   Greek → ASCII, and collapses variable oxygen-stoichiometry
   suffixes (``+δ``, ``-x``, ``+delta``, ``±y`` …) so cuprate
   oxygen-doping notations all merge into the parent compound.
   Without this ~20 BSCCO variants stayed split, hiding that
   300+ papers talk about the same compound.

2. **Confidence-weighted MODE** for legacy catalogue categories (such as
   structure_phase). A single high-confidence paper beats two
   hedged mentions; ties below a 60% share threshold fall back to
   NULL. Keeps disputed / weak signals out of the flat columns.

3. **Source-backed scientific-property semantics** — pairing, unconventional
   behavior and competing-order indicators use a separate versioned contract.
   Missing evidence remains unknown; family priors never fill observed fields.

4. **Cross-family phase sanity check** — drops ``cuprate_*`` when the
   formula has no Cu (Gemini over-applies the cuprate taxonomy to
   unfamiliar compounds like MgB₂ or bismuthates).

5. **Family fallback** — when NER doesn't emit a ``family`` for a
   material, fall back to the rule-based ``classify_family`` shared
   with the NIMS importer.

6. **Heterogeneity is not scientific dispute** — numerical spreads and
   different sample states are descriptive only. Explicit reported disputes,
   curated refutations and pre-existing governance holds are retained.

The aggregator rebuilds summaries from the current paper snapshot. Numeric
anomalies are retained in ``records`` and excluded only from affected property
views. Already-retained source-held records remain available for Archive
traceability but cannot supply current summaries. The sweep does not restore
missing historical records: that requires an independently authorized
source-history recovery, not a blind merge.

Invoked by:
  sclib-ingest --mode aggregate-materials

Typical cadence: once per daily cron run, after the incremental arXiv
harvest has finished writing ``papers.materials_extracted``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.anomaly_review import (
    ANOMALY_POLICY_VERSION,
    assess_record_anomalies,
    build_anomaly_review,
    eligible_for_property,
)
from ingestion.claims.outcomes import outcome_conflicts_with_positive

# Canonicalization + family rules live in nims.py and are shared so
# both import paths (NIMS CSV + arXiv NER) agree on the grouping key.
from ingestion.extract import formula_validator as _formula_validator
from ingestion.extract.scientific_values import legacy_scalar, record_quantity
from ingestion.index.indexer import (
    _session_factory,
    manual_overrides_table,
    materials_table,
    papers_table,
    pipeline_state_table,
    refuted_claims_table,
)
from ingestion.material_semantics import build_material_semantics
from ingestion.nims import NORMALIZE_SCHEMA_VERSION, normalize_formula
from ingestion.nims import classify_family as _classify_family
from ingestion.nims import detect_interface as _detect_interface
from ingestion.nims import parent_formula_key as _parent_formula_key
from ingestion.pressure_semantics import classify_pressure
from ingestion.property_evidence import (
    ATOMIC_SELECTION_POLICY,
    build_property_evidence,
    legacy_result_id,
)
from ingestion.result_semantics import (
    classify_result,
    is_computed_result,
    is_observed_result,
)

log = logging.getLogger(__name__)


# Re-export for backwards compat with any callers importing from this
# module directly.
__all__ = ["aggregate_from_papers", "normalize_formula"]


def _material_id(normalized: str) -> str:
    """Deterministic 100-char primary key.

    Matches the NIMS importer's scheme (``nims:<formula>``) for rows
    that already came from NIMS; for pure arXiv-sourced materials we
    use ``mat:<formula>`` so the two origins stay distinguishable.
    """
    import hashlib
    prefix = "mat"
    if len(normalized) <= 90:
        return f"{prefix}:{normalized}"
    h = hashlib.sha1(normalized.encode()).hexdigest()[:8]
    return f"{prefix}:{normalized[:80]}:{h}"


# ---------------------------------------------------------------------------
# Summary derivation helpers
# ---------------------------------------------------------------------------

# Default confidence assumed when a record doesn't report one. We use a
# middling 0.5 so a bare "yes it's true" doesn't over- or under-weight
# the vote; tune via NER prompt if we ever get well-calibrated confidences.
_DEFAULT_CONFIDENCE = 0.5
# Minimum confidence share for a weighted-mode winner to be promoted to
# the flat column. 0.6 means "60% of summed confidence points to this
# value"; anything below falls back to NULL.
_MIN_CONFIDENCE_SHARE = 0.6
# Minimum weighted share for a boolean flag to be considered "confirmed".
# Applied to each side independently: >=0.7 agreement with <0.2 dissent.
_BOOL_AGREEMENT = 0.7
_BOOL_DISSENT_MAX = 0.2
# When materials table has 2+ records we require at least this many
# voters pointing at the winning value. For single-paper materials
# we accept the single vote (otherwise everything would be NULL).
_MIN_VOTERS_MULTIPAPER = 2
# A lifecycle hold removes support from current summaries, not the historical
# existence of the source, its records, or the material. Unknown status is not
# an affirmative hold and must not be used to retire source-less NIMS rows.
_HELD_SOURCE_STATUSES = frozenset({"retracted", "withdrawn", "corrected", "disputed"})
# Numeric plausibility rules live in ingestion.anomaly_review. They are
# versioned review references, not universal physical limits or replacements.


def _source_is_held(status: Any) -> bool:
    return isinstance(status, str) and status.strip().lower() in _HELD_SOURCE_STATUSES


def _record_source_is_held(record: dict[str, Any], source_statuses: dict[str, Any]) -> bool:
    paper_id = record.get("paper_id")
    return isinstance(paper_id, str) and _source_is_held(source_statuses.get(paper_id))


def _only_held_source_support(records: Any, source_statuses: dict[str, Any]) -> bool:
    """Require a positive current hold for *every* explicitly linked record.

    Missing sources, unknown status, malformed records and absent extractions
    are not evidence of retraction. This is deliberately narrower than general
    review eligibility, and never infers identity from a formula or DOI.
    """
    return isinstance(records, list) and bool(records) and all(
        isinstance(record, dict)
        and _record_source_is_held(record, source_statuses)
        for record in records
    )


# ---------------------------------------------------------------------------
# P0: Override / refuted-claim infrastructure
# ---------------------------------------------------------------------------

class _OverrideEntry:
    """In-memory representation of one manual_overrides row."""
    __slots__ = ("field", "is_cap", "reason", "reference_id", "source", "value_str")

    def __init__(self, field: str, value_str: str, is_cap: bool,
                 source: str, reason: str | None, reference_id: str | None = None):
        self.field = field
        self.value_str = value_str
        self.is_cap = is_cap
        self.source = source
        self.reason = reason
        self.reference_id = reference_id

    @property
    def numeric_value(self) -> float | None:
        try:
            value = float(self.value_str)
            return value if math.isfinite(value) else None
        except (ValueError, TypeError):
            return None

    @property
    def string_value(self) -> str:
        """Strip surrounding double-quotes for enum overrides."""
        s = self.value_str.strip()
        if s.startswith('"') and s.endswith('"'):
            return s[1:-1]
        return s


class _RefutedEntry:
    __slots__ = ("canonical", "claim_type", "claimed_tc", "notes")

    def __init__(self, canonical: str, claim_type: str,
                 claimed_tc: float | None, notes: str | None):
        self.canonical = canonical
        self.claim_type = claim_type
        self.claimed_tc = claimed_tc
        self.notes = notes


# These caches are populated once per `aggregate_from_papers()` run.
_override_cache: dict[str, list[_OverrideEntry]] = {}
_refuted_cache: dict[str, _RefutedEntry] = {}


async def _load_all_overrides(db: Any) -> dict[str, list[_OverrideEntry]]:
    """Load all manual_overrides into a dict keyed by canonical formula."""
    result: dict[str, list[_OverrideEntry]] = defaultdict(list)
    rows = (await db.execute(
        select(
            manual_overrides_table.c.id,
            manual_overrides_table.c.canonical,
            manual_overrides_table.c.field,
            manual_overrides_table.c.override_value,
            manual_overrides_table.c.is_cap,
            manual_overrides_table.c.source,
            manual_overrides_table.c.reason,
        )
    )).all()
    for row_id, canonical, field, value, is_cap, source, reason in rows:
        result[canonical].append(
            _OverrideEntry(field, value, is_cap, source, reason,
                           reference_id=f"manual_overrides:{row_id}")
        )
    return dict(result)


async def _load_all_refuted(db: Any) -> dict[str, _RefutedEntry]:
    """Load all refuted_claims into a dict keyed by canonical formula."""
    result: dict[str, _RefutedEntry] = {}
    rows = (await db.execute(
        select(
            refuted_claims_table.c.canonical,
            refuted_claims_table.c.claim_type,
            refuted_claims_table.c.claimed_tc,
            refuted_claims_table.c.notes,
        )
    )).all()
    for canonical, claim_type, claimed_tc, notes in rows:
        # If multiple rows for same canonical, keep the first (shouldn't
        # happen with current seed data, but defensive).
        if canonical not in result:
            result[canonical] = _RefutedEntry(
                canonical, claim_type, claimed_tc, notes
            )
    return result


def _apply_overrides(
    summary: dict[str, Any],
    overrides: list[_OverrideEntry],
) -> list[str]:
    """Apply only legacy categorical overrides to a computed summary dict.

    Returns a list of human-readable notes describing what was changed,
    for appending to review_reason.
    """
    notes: list[str] = []

    # Numeric requests have no source-backed correction identity. They are
    # review inputs, never measurements or permission to replace a value.
    by_field: dict[str, list[_OverrideEntry]] = defaultdict(list)
    for ov in overrides:
        by_field[ov.field].append(ov)

    for field, entries in by_field.items():
        # Exact overrides (is_cap=False) first
        exact = [e for e in entries if not e.is_cap]

        if exact:
            ov = exact[0]  # take the first exact override
            if field in ("pairing_symmetry", "gap_structure",
                         "competing_order", "crystal_structure",
                         "space_group", "structure_phase"):
                old = summary.get(field)
                summary[field] = ov.string_value
                notes.append(f"{field}: {old!r} -> {ov.string_value!r} (override: {ov.source})")

    return notes


def _override_review_inputs(overrides: list[_OverrideEntry] | None) -> list[dict[str, Any]]:
    """Non-authorizing numeric review references, without source free text."""
    inputs = []
    for entry in overrides or ():
        value = entry.numeric_value
        categorical_targets = {
            "pairing_symmetry", "gap_structure", "competing_order", "crystal_structure",
            "space_group", "structure_phase",
        }
        if entry.field in categorical_targets:
            continue
        mode = "upper_reference" if entry.is_cap else "unreviewed_exact_override"
        # A malformed legacy numeric request remains an unresolved review
        # input; silently dropping it could expose previously withheld data.
        identity = json.dumps([entry.field, value if value is not None else entry.value_str, mode],
                              separators=(",", ":"))
        reference_id = entry.reference_id or (
            "unpersisted_override:" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        )
        inputs.append({"field": entry.field, "threshold": value,
                       "reference_id": reference_id, "mode": mode})
    return sorted(inputs, key=lambda item: (item["field"], item["mode"], item["reference_id"]))


def _confidence(r: dict[str, Any]) -> float:
    """Best-effort float confidence, clamped to [0, 1]."""
    v = r.get("confidence")
    if not isinstance(v, (int, float)):
        return _DEFAULT_CONFIDENCE
    return max(0.0, min(1.0, float(v)))


def _paper_source_label(paper_id: Any) -> str | None:
    """Human-readable provenance label for material summary snippets."""
    if not isinstance(paper_id, str):
        return None
    pid = paper_id.strip()
    if not pid:
        return None
    if pid.startswith("arxiv:"):
        return f"arXiv:{pid.removeprefix('arxiv:')}"
    if pid.startswith("aps:"):
        return f"DOI: {pid.removeprefix('aps:')}"
    if pid.startswith("doi:"):
        return f"DOI: {pid.removeprefix('doi:')}"
    if pid.startswith("nims:"):
        return f"NIMS:{pid.removeprefix('nims:')}"
    return pid


def _source_scalar(record: dict[str, Any], key: str) -> float | None:
    """Canonical source-backed point; never a midpoint, bound or cached guess."""
    return legacy_scalar(record_quantity(record, key, *(("tc",) if key == "tc_kelvin" else ())))


def _max_numeric(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [value for r in records if (value := _source_scalar(r, key)) is not None]
    return max(vals) if vals else None


def _corroborated_max(
    records: list[dict[str, Any]],
    key: str,
) -> tuple[float | None, int]:
    """Bibliographic numeric-pool selection heuristic, not confirmation.

    NER sometimes mistakes a paper's gap energy (2Δ/k_B), Hc2
    extrapolation, or Curie / structural transition for the SC Tc.
    Taking plain ``max(tc_kelvin)`` then lets a single bad paper set
    the headline Tc — MgB₂ at 79 K is the audit example where one
    paper's gap-derived number beat 200 papers' correct 39 K.

    Rule: walk candidate paper-maxima from highest down. For each
    candidate ``c``, count how many *distinct papers* report
    ``tc_kelvin >= c``. Accept the first ``c`` where that count
    meets ``min_support``:

      n_papers | min_support
      -------- | ------------
         1–4   |      1  (accept the max — rare materials)
         5–39  |      2  (need one corroborating paper)
        40–199 |   n // 20  (5% of papers)
        ≥ 200  |     10  (cap so hundreds-of-papers materials stay
                          resistant to a small cluster of NER errors)

    The strict ``v >= c`` support rule (rather than a tolerance band)
    is deliberate: the previous version let legitimate high-Tc papers
    at 133 K "confirm" a spurious 150 K claim, because 133 > 150·0.85.
    Requiring papers to claim at least as high as the candidate
    avoids that false confirmation.

    Source IDs are not independent laboratories, studies or replications.
    Returns (value, bibliographic_source_count); it does not infer acceptance.
    """
    per_paper: dict[str, float] = {}
    for r in records:
        v = _source_scalar(r, key)
        pid = r.get("paper_id")
        if isinstance(v, (int, float)) and v > 0 and isinstance(pid, str) and pid and v > per_paper.get(pid, 0):
            per_paper[pid] = float(v)
    if not per_paper:
        return None, 0

    values = sorted(per_paper.values(), reverse=True)
    n_papers = len(values)
    if n_papers < 5:
        candidate = values[0]
        # Rare materials may publish the maximum from a single paper, but the
        # provenance label must still report the number that actually supports
        # that exact value. Returning ``n_papers`` here used to label a 93 K
        # outlier plus a 91 K paper as "confirmed by 2 papers".
        support = sum(1 for value in values if value >= candidate)
        return candidate, support

    min_support = max(2, min(10, n_papers // 20))
    for cand in values:
        support = sum(1 for v in values if v >= cand)
        if support >= min_support:
            return cand, support

    # Unreachable when n_papers >= 5 (the smallest value always has
    # support = n_papers), but fall back for safety.
    return values[-1], n_papers


def _record_is_theoretical(r: dict[str, Any]) -> bool:
    """Compatibility wrapper: False does not imply Observed; use the full policy."""
    return is_computed_result(r)


def _median_numeric(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [value for r in records if (value := _source_scalar(r, key)) is not None]
    return float(median(vals)) if vals else None


def _weighted_mode_str(
    records: list[dict[str, Any]],
    key: str,
) -> str | None:
    """Confidence-weighted mode for a string field.

    Returns the value whose summed confidence is highest, but only if
    - it has at least ``_MIN_VOTERS_MULTIPAPER`` voters (when the
      material has >=2 records overall); and
    - its share of total confidence is >= ``_MIN_CONFIDENCE_SHARE``.

    Otherwise returns ``None`` so we don't confidently publish a weak
    consensus — better an empty cell than a wrong one.

    Case-preserves the original winner spelling ("d-wave", not
    "D-wave") by keying on the lowercased form internally and
    emitting the most common cased variant.
    """
    votes: dict[str, float] = defaultdict(float)
    voters: dict[str, set[str]] = defaultdict(set)
    case_variants: dict[str, Counter[str]] = defaultdict(Counter)
    for r in records:
        v = r.get(key)
        if not isinstance(v, str) or not v.strip():
            continue
        vl = v.strip().lower()
        if vl == "unknown":
            continue
        w = _confidence(r)
        votes[vl] += w
        pid = r.get("paper_id") or ""
        voters[vl].add(pid)
        case_variants[vl][v.strip()] += 1

    if not votes:
        return None
    total = sum(votes.values())
    top_key, top_w = max(votes.items(), key=lambda kv: kv[1])

    if len(records) >= 2 and len(voters[top_key]) < _MIN_VOTERS_MULTIPAPER:
        return None
    if total > 0 and (top_w / total) < _MIN_CONFIDENCE_SHARE:
        return None

    # Pick the most common casing among records that voted for this
    # lowercased winner. Falls back to the first seen if counts tie.
    return case_variants[top_key].most_common(1)[0][0]


def _weighted_boolean(
    records: list[dict[str, Any]],
    key: str,
) -> bool | None:
    """Dual-threshold boolean consensus.

    - Confirms **True** iff weighted True-share ≥ 0.7 AND False-share < 0.2
    - Confirms **False** iff weighted False-share ≥ 0.7 AND True-share < 0.2
    - Otherwise returns None (disputed / weak / silent)

    Records that don't state this flag are ignored (not counted as
    "False"). A common NER failure mode is emitting ``is_unconventional=False``
    as a default; with this rule a single unopposed False doesn't
    get promoted to a confident column — it needs agreement.
    """
    true_w = 0.0
    false_w = 0.0
    for r in records:
        v = r.get(key)
        if v is True:
            true_w += _confidence(r)
        elif v is False:
            false_w += _confidence(r)
    total = true_w + false_w
    if total <= 0:
        return None
    t_share = true_w / total
    f_share = false_w / total
    if t_share >= _BOOL_AGREEMENT and f_share < _BOOL_DISSENT_MAX:
        return True
    if f_share >= _BOOL_AGREEMENT and t_share < _BOOL_DISSENT_MAX:
        return False
    return None


# Per-column length budgets — must match the VARCHAR(N) widths in
# api/models/db.py and api/alembic/versions/0002_materials_v2_schema.py.
# Strings exceeding the column width crash the aggregator
# (asyncpg.StringDataRightTruncationError). The NER occasionally
# returns a sentence-long description into a field that's supposed to
# carry a single tag (e.g. ``crystal_structure`` got an entire phrase
# about Fe-vacancy ordering). Anything past the budget is almost
# certainly off-spec and we treat it as "no value" rather than
# truncating mid-word, since a half-sentence aggregate is misleading.
_FIELD_MAX_LEN: dict[str, int] = {
    "crystal_structure": 100,
    "space_group": 50,
    "structure_phase": 50,
    "gap_structure": 50,
    "pairing_symmetry": 100,
    "hc2_conditions": 200,
    "tc_max_conditions": 300,
    "competing_order": 100,
    "pressure_type": 50,
    "sample_form": 50,
    "substrate": 100,
    "doping_type": 50,
    "review_reason": 200,
    "family": 50,
}


def _clip(field: str, value: Any) -> Any:
    """Drop string values longer than the destination column.

    Returns the original value untouched when the field has no
    configured budget or the value is not a string within budget.
    Returns ``None`` when the value is over-long — the caller writes
    that NULL into the materials table instead of trying to truncate
    a partial sentence into a tag column.
    """
    if not isinstance(value, str):
        return value
    cap = _FIELD_MAX_LEN.get(field)
    if cap is None or len(value) <= cap:
        return value
    log.debug(
        "_clip: dropping %s value of length %d > cap %d",
        field, len(value), cap,
    )
    return None


def _first_non_null(records: list[dict[str, Any]], key: str) -> Any:
    for r in records:
        v = r.get(key)
        if v is not None and v != "":
            return v
    return None


def _earliest_non_null(
    records: list[dict[str, Any]], key: str,
) -> Any:
    """First non-null value sorted by paper year ascending.

    Used for ``crystal_structure`` / ``space_group`` — the oldest paper
    that reports the crystal structure is the canonical source, because
    later papers either reconfirm or refine that structure but rarely
    redefine it. Falls back to ``_first_non_null`` order if year is
    missing everywhere.
    """
    with_year = sorted(
        (r for r in records if r.get(key) not in (None, "")
         and isinstance(r.get("year"), int)),
        key=lambda r: r["year"],
    )
    if with_year:
        return with_year[0][key]
    return _first_non_null(records, key)


def _has_cu(formula: str) -> bool:
    """True iff the formula token-stream contains the Cu element.

    Uses element tokenization (``[A-Z][a-z]?``) on the original-case
    formula. Matching "cu" in a lowercased form would false-hit on
    e.g. "CuI4" → OK, "BCS" → no... but safer to tokenize.
    """
    return "Cu" in re.findall(r"[A-Z][a-z]?", formula)


def _sanity_check_structure_phase(
    formula_raw: str,
    structure_phase: str | None,
) -> str | None:
    """Reject a ``structure_phase`` that's inconsistent with the formula.

    Gemini systematically over-tags unfamiliar compounds with
    ``cuprate_*`` phase labels (e.g. MgB₂ → cuprate_123) and confuses
    cuprate sub-phases. Drop only HIGH-CONFIDENCE contradictions
    (return None = "no phase", never fabricate one); leave anything
    ambiguous untouched.
    """
    if not structure_phase:
        return None
    if structure_phase.startswith("cuprate") and not _has_cu(formula_raw):
        return None
    toks = re.findall(r"[A-Z][a-z]?", formula_raw)
    has_cu = "Cu" in toks
    # Normalize "cuprate_123" / "123" to a bare phase token (exact
    # match — "1232" must NOT be treated as "123").
    p = structure_phase.lower().removeprefix("cuprate_").strip()
    # "123" == R Ba₂ Cu₃ O₇ (YBCO): defined by the Ba₂Cu₃ block. An
    # electron-doped T′ cuprate R₂₋ₓCeₓCuO₄ (Ce present, Ba absent)
    # tagged 123 is a recurrent Gemini error.
    if p == "123" and has_cu and "Ce" in toks and "Ba" not in toks:
        return None
    # "214" == La₂CuO₄-type single CuO₂ layer (La/Sr). Hg-/Tl-based
    # cuprates are the 12(n-1)n / 22(n-1)n homologous series and are
    # never the 214 phase.
    if p == "214" and has_cu and ("Hg" in toks or "Tl" in toks):
        return None
    return structure_phase


def _derive_summary(
    formula_raw: str,
    records: list[dict[str, Any]],
    *,
    overrides: list[_OverrideEntry] | None = None,
    refuted: _RefutedEntry | None = None,
    current_year: int | None = None,
    source_statuses: dict[str, str | None] | None = None,
    legacy_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive field-scoped scientific summaries while retaining current raw input.

    Numeric anomalies and legacy numeric override requests never delete a
    source record or manufacture a measurement. Eligibility is versioned and
    independent of the pre-existing non-numeric catalogue visibility policy.
    """
    raw_records = records
    # Callers may retain held records for Archive traceability. They cannot
    # contribute to any numerical, categorical or bibliographic summary.
    # Keeping this in the pure derivation also protects non-driver callers.
    records = [record for record in raw_records
               if not _record_source_is_held(record, source_statuses or {})]
    norm_key = normalize_formula(formula_raw)
    scope_id = _material_id(norm_key)
    current_year = datetime.now(UTC).year if current_year is None else current_year
    if isinstance(current_year, bool) or not isinstance(current_year, int) or not 1900 <= current_year <= 9999:
        raise ValueError("current_year must be an explicit integer chronology reference")
    _ner_fam = _weighted_mode_str(records, "family")
    _rule_fam = _classify_family(formula_raw)
    if _rule_fam == "elemental":
        family = "elemental"
    elif _rule_fam == "bis2_layered" and _ner_fam in (None, "chalcogenide", "bismuthate"):
        family = "bis2_layered"
    else:
        family = _ner_fam or _rule_fam
    compound_thresholds = _override_review_inputs(overrides)
    anomaly_context = {"policy_version": ANOMALY_POLICY_VERSION, "family": family,
                       "compound_thresholds": compound_thresholds,
                       "selection_policy": ATOMIC_SELECTION_POLICY,
                       "current_year": current_year}
    assessments = [assess_record_anomalies(r, scope_id=scope_id, family=family,
                                          compound_thresholds=compound_thresholds,
                                          current_year=current_year)
                   for r in records]

    def eligible(field: str) -> list[dict[str, Any]]:
        return [record for record, assessment in zip(records, assessments)
                if eligible_for_property(assessment, field)]

    # -----------------------------------------------------------------
    # A2: Evidence-tier split — separate experimental vs theoretical
    # -----------------------------------------------------------------
    # Evidence split via the single-source-of-truth classifier so a
    # DFT/Eliashberg record NER left evidence_type-untagged (or tagged
    # only with the legacy ambiguous "primary") is counted as theory,
    # not smuggled into the experimental headline (audit cat. E).
    theo_records = [r for r in records if _record_is_theoretical(r)]
    exp_records = [
        r for r in records
        if is_observed_result(r)
        and classify_result(r).source_role != "cited"
    ]
    def origin_pool(field: str, *, computed: bool = False) -> list[dict[str, Any]]:
        return [r for r in eligible(field) if not outcome_conflicts_with_positive(r) and (
            _record_is_theoretical(r) if computed else
            is_observed_result(r) and classify_result(r).source_role != "cited"
        )]

    tc_max_exp, _ = _corroborated_max(origin_pool("tc_max_experimental"), "tc_kelvin")
    tc_max_theo, _ = _corroborated_max(origin_pool("tc_max_theoretical", computed=True), "tc_kelvin")
    headline_exp = origin_pool("tc_max")
    headline_theo = origin_pool("tc_max", computed=True)
    headline_exp_max, sup_exp = _corroborated_max(headline_exp, "tc_kelvin")
    headline_theo_max, sup_theo = _corroborated_max(headline_theo, "tc_kelvin")
    dominant_evidence = _classify_evidence(exp_records, theo_records, records)

    # tc_max is the record-high Tc in ANY condition (high pressure,
    # thin film, doped, …) BUT reflects EXPERIMENTAL reality whenever
    # any experimental evidence exists — a pure DFT/Eliashberg
    # prediction must never be presented as the measured record-high
    # (audit cat. E). The prediction is still surfaced separately via
    # tc_max_theoretical, and the conditions string is tagged
    # "theoretical" for prediction-only materials. Each side keeps the
    # corroboration rule (≥2 papers) against single-paper outliers.
    if headline_exp_max is not None:
        tc_max, tc_max_support, _tc_basis = headline_exp_max, sup_exp, "experimental"
    elif headline_theo_max is not None:
        tc_max, tc_max_support, _tc_basis = headline_theo_max, sup_theo, "theoretical"
    else:
        tc_max, tc_max_support, _tc_basis = None, 0, None

    # Ambient is a pressure condition, not a family/sample/regime default.
    # Require same-result explicit pressure evidence and an observed Tc.
    ambient_records = [
        r for r in origin_pool("tc_ambient")
        if _source_scalar(r, "tc_kelvin") is not None
        and _source_scalar(r, "tc_kelvin") > 0
        and r.get("ambient_sc") is not False
        and classify_pressure(r).pressure_state == "explicit_ambient"
    ]
    # Apply the same corroboration rule here so an outlier
    # ambient-pressure claim doesn't dominate either.
    tc_ambient, _ = _corroborated_max(ambient_records, "tc_kelvin")

    # These catalogue views can have different review filters/support pools.
    # Do not copy a value across views to force an ordering invariant.
    # Numerical spread is described by material_semantics below, never by a
    # scientific-dispute flag. States/conditions may differ across reports.

    # No eligible ambient observation is not a material-wide negative label.
    ambient_sc = True if ambient_records else None

    competing_order = _weighted_mode_str(records, "competing_order")
    t_cdw = _max_numeric(eligible("t_cdw_k"), "t_cdw_k")
    t_sdw = _max_numeric(eligible("t_sdw_k"), "t_sdw_k")
    t_afm = _max_numeric(eligible("t_afm_k"), "t_afm_k")

    has_competing_order = None  # Shared source-backed contract resolves below.

    # tc_max_conditions: pick the record tying the max and format as
    # "P={p} GPa, <sample>, <measurement> (<source>:<id>)". Appends a
    # bibliographic support note; counts do not establish replication.
    tc_max_cond = None
    if tc_max is not None:
        _basis_recs = headline_theo if _tc_basis == "theoretical" else headline_exp
        _tc_scope = _material_id(normalize_formula(formula_raw))
        for r in sorted(_basis_recs, key=lambda item: legacy_result_id(item, scope_id=_tc_scope)):
            if _source_scalar(r, "tc_kelvin") == tc_max:
                parts: list[str] = []
                if _tc_basis == "theoretical":
                    parts.append("theoretical (DFT/computational)")
                pressure = classify_pressure(r)
                if pressure.pressure_state == "explicit_ambient":
                    parts.append("ambient")
                elif pressure.pressure_state == "reported" and pressure.pressure_gpa is not None:
                    value = f"{pressure.pressure_gpa:g}"
                    if pressure.uncertainty_gpa is not None:
                        value += f" ± {pressure.uncertainty_gpa:g}"
                    parts.append(f"P={'approximately ' if pressure.approximate else ''}{value} GPa")
                elif pressure.pressure_state == "reported" and pressure.relation == "interval":
                    parts.append(f"P=[{pressure.value_lower_gpa:g}, {pressure.value_upper_gpa:g}] GPa")
                elif pressure.pressure_state == "reported":
                    operator = {"lt": "<", "le": "≤", "gt": ">", "ge": "≥"}[pressure.relation]
                    value = pressure.value_upper_gpa if pressure.relation in {"lt", "le"} else pressure.value_lower_gpa
                    parts.append(f"P {operator} {value:g} GPa")
                elif pressure.pressure_state == "ambiguous":
                    parts.append("pressure unresolved")
                else:
                    parts.append("pressure not reported")
                if r.get("sample_form"):
                    parts.append(str(r["sample_form"]))
                if r.get("measurement") and str(r["measurement"]).lower() != "unknown":
                    parts.append(str(r["measurement"]))
                source_label = _paper_source_label(r.get("paper_id"))
                if source_label:
                    parts.append(source_label)
                tc_max_cond = ", ".join(parts) or None
                break
        if tc_max_support >= 2:
            note = f"numeric-pool support from {tc_max_support} bibliographic identifiers (not independent replication)"
            tc_max_cond = (
                f"{tc_max_cond}, {note}" if tc_max_cond else note
            )

    paper_ids = {r.get("paper_id") for r in records if r.get("paper_id")}
    years = [
        r.get("year") for r in eligible("year")
        if isinstance(r.get("year"), int) and r.get("year") > 1900
    ]
    arxiv_year = min(years) if years else None

    # Structure phase with cross-family sanity check
    raw_phase = _weighted_mode_str(records, "structure_phase")
    structure_phase = _sanity_check_structure_phase(formula_raw, raw_phase)

    is_unconventional = None  # Never populated by a family rule or vote.

    # An explicit dispute must not be voted away by more numerous silent or
    # negative records. Existing database holds are also sticky at upsert.
    disputed = any(record.get("disputed") is True for record in records)

    # -------------------------------------------------------------------
    # Sanity gate: needs_review
    # -------------------------------------------------------------------
    # The material-level flag is retained for a material with reported Tc but
    # no eligible headline Tc. Mixed records remain discoverable through their
    # valid properties; anomaly_review exposes every affected raw result.
    has_reported_tc = any(r.get("tc_kelvin") is not None for r in records)
    tc_review_required = has_reported_tc and tc_max is None and any(
        not eligible_for_property(assessment, "tc_max") for assessment in assessments
    )
    source_support_unavailable = bool(raw_records) and not records
    needs_review = tc_review_required or source_support_unavailable
    review_reason: str | None = (
        "source_support_unavailable: current linked sources require review"
        if source_support_unavailable else
        f"numeric_review_pending:{ANOMALY_POLICY_VERSION}:tc_max"
        if tc_review_required else None
    )

    # T1.3 (P3a): non-superconductor contaminants NER scraped as
    # "materials". Two random-100 audits independently recurred CMR
    # manganites (LaMnO3, La0.65Ca0.35MnO3, La0.67Sr0.33MnO3) — these
    # are ferromagnetic/AFM, NOT superconductors (a ~370 K Curie temp
    # often mis-read as Tc). Soft-flag (reversible, admin can clear).
    # Mn-based SCs (MnP/MnSi) carry no oxygen, so the O requirement
    # excludes them; Cu/Fe exclusion protects Mn-doped cuprates/iron.
    if not needs_review:
        _els = set(re.findall(r"[A-Z][a-z]?", formula_raw))
        _bare = re.sub(r"[^a-z0-9]", "", formula_raw.lower())
        if (
            "Mn" in _els and "O" in _els
            and (_els & {"La", "Pr", "Nd", "Sm", "Y",
                         "Ca", "Sr", "Ba", "Bi"})
            and "Cu" not in _els and "Fe" not in _els
            # CMR manganites are oxides — never oxysulfides. Excludes
            # Mn-doped BiS-type SCs like Bi4-xMnxO4S3 (chalcogen).
            and not (_els & {"S", "Se", "Te"})
        ):
            needs_review = True
            review_reason = "non_sc_material_suspected: CMR/AFM manganite"
        elif _bare in {
            # bare ferroelectric / band-insulator substrates (NOT
            # SrTiO3/KTaO3 — those have real doped-SC literature).
            "batio3", "pbtio3", "catio3", "laalo3", "mgo",
            "al2o3", "sio2", "srzro3", "bazro3", "latio3", "tio2",
        }:
            needs_review = True
            review_reason = (
                "non_sc_material_suspected: ferroelectric/insulator"
            )

    # P2 A5: Interface material detection (FeSe/STO → overlayer + substrate)
    norm_key = normalize_formula(formula_raw)
    overlayer, substrate_mat = _detect_interface(norm_key)

    # Atomic source selection applies the same versioned, field-scoped review
    # context. Raw records and unrelated properties remain intact.
    atomic = build_property_evidence(
        records, scope_id=_material_id(norm_key), include_joint_epc=False,
        property_fields=("hc2_tesla", "lattice_params", "crystal_structure", "space_group"),
        anomaly_context=anomaly_context,
    )
    properties = atomic["properties"]
    structural_result = next((properties[field]["selected"] for field in (
        "lattice_params", "crystal_structure", "space_group",
    ) if properties[field]["selected"] is not None), None)
    structural_group = structural_result["structure"] if structural_result else {}
    hc2_result = properties["hc2_tesla"]["selected"]

    # Every string going into a varchar column passes through _clip
    # so a chatty NER hallucination (e.g. "single Fe vacancy for every
    # eight Fe-sites arranged in a √10×√8 parallelogram structure"
    # being dropped into ``crystal_structure``) doesn't crash the
    # whole aggregator with a StringDataRightTruncationError. Values
    # over the column budget become NULL — better empty than wrong.
    summary = {
        "formula": formula_raw[:200],
        "formula_normalized": norm_key[:200],
        "family":            _clip("family", family),
        "tc_max": tc_max,
        "tc_max_conditions": _clip("tc_max_conditions", tc_max_cond),
        "tc_ambient": tc_ambient,
        "dominant_evidence": dominant_evidence,
        "tc_max_experimental": tc_max_exp,
        "tc_max_theoretical": tc_max_theo,
        "ambient_sc": ambient_sc,
        "arxiv_year": arxiv_year,
        "total_papers": len(paper_ids),
        # One complete source result; unknown components stay unknown. The
        # independent structure_phase consensus below is a catalogue category,
        # not a constituent of this source's crystallographic observation.
        "crystal_structure": _clip("crystal_structure",
                                   structural_group.get("crystal_structure")),
        "space_group":       _clip("space_group",
                                   structural_group.get("space_group")),
        "structure_phase":   _clip("structure_phase", structure_phase),
        "lattice_params":    (properties["lattice_params"]["selected"]["value"]
                              if properties["lattice_params"]["selected"] else None),
        # Reported pairing is resolved by the shared semantics below, never a
        # transient vote that could be mistaken for a source-backed binding.
        "pairing_symmetry":  None,
        "gap_structure":     _clip("gap_structure",
                                   _weighted_mode_str(records, "gap_structure")),
        "hc2_tesla":         hc2_result["value"] if hc2_result else None,
        "hc2_conditions":    _clip("hc2_conditions",
                                   hc2_result["conditions"].get("hc2_conditions") if hc2_result else None),
        "lambda_eph":        _max_numeric(eligible("lambda_eph"), "lambda_eph"),
        "omega_log_k":       _max_numeric(eligible("omega_log_k"), "omega_log_k"),
        "rho_s_mev":         _max_numeric(eligible("rho_s_mev"), "rho_s_mev"),
        # Competing orders
        "t_cdw_k":           t_cdw,
        "t_sdw_k":           t_sdw,
        "t_afm_k":           t_afm,
        "rho_exponent":      _median_numeric(eligible("rho_exponent"), "rho_exponent"),
        "competing_order":   _clip("competing_order", competing_order),
        "has_competing_order": has_competing_order,
        # Samples / pressure
        "sample_form":       _clip("sample_form",
                                   _weighted_mode_str(records, "sample_form")),
        "substrate":         _clip("substrate",
                                   _first_non_null(records, "substrate")),
        "pressure_type":     _clip("pressure_type",
                                   _weighted_mode_str(records, "pressure_type")),
        "doping_type":       _clip("doping_type",
                                   _weighted_mode_str(records, "doping_type")),
        "doping_level":      _median_numeric(eligible("doping_level"), "doping_level"),
        # Scientific flags remain unknown until source-backed resolution.
        "is_unconventional":   is_unconventional,
        "disputed":            disputed,
        # P2: Interface material decomposition
        "formula_substrate":   substrate_mat[:200] if substrate_mat else None,
        "formula_overlayer":   overlayer[:200] if overlayer else None,
        # Best credibility tier across all records (T1 best → T3 worst)
        "best_credibility_tier": min(
            (r.get("credibility_tier") for r in records if r.get("credibility_tier")),
            default=None,
        ),
        # Automatic sanity gate
        "needs_review":        needs_review,
        "review_reason":       _clip("review_reason", review_reason),
        "records": raw_records,
        "anomaly_context": anomaly_context,
        "anomaly_review": build_anomaly_review(
            raw_records, scope_id=scope_id, family=family,
            compound_thresholds=compound_thresholds,
            current_year=current_year,
        ),
    }

    # -------------------------------------------------------------------
    # Legacy categorical overrides only; numeric requests remain review inputs.
    # -------------------------------------------------------------------
    if overrides:
        override_notes = _apply_overrides(summary, overrides)
        if override_notes:
            existing_reason = summary.get("review_reason") or ""
            note_str = "; ".join(override_notes)
            if existing_reason:
                summary["review_reason"] = _clip(
                    "review_reason",
                    f"{existing_reason}; overrides_applied: {note_str}",
                )
            else:
                summary["review_reason"] = _clip(
                    "review_reason", f"overrides_applied: {note_str}",
                )
            log.info("overrides applied to %s: %s", formula_raw, note_str)

    # -------------------------------------------------------------------
    # Step 0.4: Refuted claim → force disputed=True
    # -------------------------------------------------------------------
    if refuted:
        summary["disputed"] = True
        reason_prefix = summary.get("review_reason") or ""
        refuted_note = f"refuted:{refuted.claim_type}"
        if reason_prefix:
            summary["review_reason"] = _clip(
                "review_reason", f"{reason_prefix}; {refuted_note}",
            )
        else:
            summary["review_reason"] = refuted_note
        log.info(
            "refuted claim matched: %s (%s)", formula_raw, refuted.claim_type,
        )

    # Source precision is retained. Formatting belongs in the UI; neither a
    # legacy cap nor rounding may create a new unsupported scalar here.
    if hc2_result is None or summary.get("hc2_tesla") != hc2_result["value"]:
        summary["hc2_conditions"] = None

    # Existing governance holds and legacy summary inputs are review context,
    # not accepted physical observations. Keep them separate from raw records.
    semantic_legacy = {**summary, **(legacy_summary or {})}
    if summary["disputed"] is True or semantic_legacy.get("disputed") is True:
        summary["disputed"] = True
        semantic_legacy["disputed"] = True
    semantics = build_material_semantics(
        raw_records, scope_id=scope_id, family=family,
        legacy_summary=semantic_legacy, source_statuses=source_statuses,
    )
    summary["material_semantics"] = semantics
    for field in ("pairing_symmetry", "is_unconventional", "has_competing_order"):
        property_view = semantics["properties"][field]
        summary[field] = property_view["value"] if property_view["status"] == "reported" else None

    # SC11: raw and locally linked text remain pending relation proposals.
    # No authoritative source-revision/curator relation workflow exists yet;
    # a legacy vote, override, or exact quotation cannot populate these aliases.
    # Original records and persisted override decisions remain untouched.
    for field in ("structure_phase", "crystal_structure", "space_group"):
        summary[field] = None

    return summary


# A material counts as evidence-"dominant" (not "mixed") when one side
# holds at least this share of the primary (non-cited) records. Without
# it a single stray DFT record would demote an overwhelmingly
# experimentally-established SC (e.g. Ba1-xKxFe2As2: 78 records, a
# handful theoretical) from "experimental" to "mixed", losing signal.
_EVIDENCE_DOMINANCE = 0.75


def _classify_evidence(
    exp_records: list[dict[str, Any]],
    theo_records: list[dict[str, Any]],
    all_records: list[dict[str, Any]],
) -> str | None:
    """Classify dominant evidence type for a material.

    Returns "experimental", "theoretical", "mixed", "cited_only", or
    None. When both kinds are present, the majority side wins if it
    holds >= _EVIDENCE_DOMINANCE of the primary records; only a genuine
    contest (neither side dominant) is "mixed".
    """
    # Count via the same single-source-of-truth classifier used for
    # the tc split, so dominant_evidence can't disagree with which
    # pool drove the headline tc_max.
    n_cited = sum(
        1 for r in all_records if classify_result(r).source_role == "cited"
    )
    n_theo = sum(
        1 for r in all_records
        if classify_result(r).source_role != "cited" and is_computed_result(r)
    )
    n_exp = sum(
        1 for r in all_records
        if classify_result(r).source_role != "cited" and is_observed_result(r)
    )
    total = len(all_records)
    if total == 0:
        return None
    # All cited → "cited_only"
    if n_cited == total:
        return "cited_only"
    if n_exp > 0 and n_theo == 0:
        return "experimental"
    if n_theo > 0 and n_exp == 0:
        return "theoretical"
    if n_exp > 0 and n_theo > 0:
        primary = n_exp + n_theo
        if n_exp / primary >= _EVIDENCE_DOMINANCE:
            return "experimental"
        if n_theo / primary >= _EVIDENCE_DOMINANCE:
            return "theoretical"
        return "mixed"
    return None


def _lattice_params(records: list[dict[str, Any]]) -> dict[str, float] | None:
    """Assemble {a, c} from the first record that has numeric lattice_a/c."""
    for r in records:
        a = r.get("lattice_a")
        c = r.get("lattice_c")
        if isinstance(a, (int, float)) or isinstance(c, (int, float)):
            out: dict[str, float] = {}
            if isinstance(a, (int, float)):
                out["a"] = float(a)
            if isinstance(c, (int, float)):
                out["c"] = float(c)
            return out or None
    return None


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

# Confidence floor: records below this threshold are dropped before
# they contribute to a material's summary, so a hallucinated "UO2 Tc=400K
# conf=0.2" can't pollute the top of the list.
_MIN_CONFIDENCE = 0.3


# Match either ``$_{...}$`` or ``_{...}`` LaTeX subscripts so the
# captured group can be substituted back inline. Used by
# ``_clean_display`` to flatten ``Bi_{2}Sr_{2}CaCu_{2}O_{8+δ}`` to
# ``Bi2Sr2CaCu2O8+δ`` for the materials.formula column.
_LATEX_SUB_DISPLAY = re.compile(r"\$?_\{([^}]+)\}\$?")
_LATEX_DOLLAR_DISPLAY = re.compile(r"\$([^$]*)\$")


def _clean_display(raw: str) -> str:
    """Strip LaTeX math-mode + subscript markup from a display formula.

    The grouping key (``normalize_formula``) already does this for the
    purpose of folding duplicates; this helper does the same for the
    ``materials.formula`` column the UI surfaces. Without it, NER
    output like ``H$_{3}$S`` rendered as raw LaTeX in tooltips and
    badges, even though the row had the right normalized id.

    Conservative: keeps unicode (δ, subscripts already in the source),
    only removes the LaTeX scaffolding.
    """
    # Remove ``$_{xyz}$`` and bare ``_{xyz}`` → ``xyz``
    s = _LATEX_SUB_DISPLAY.sub(r"\1", raw)
    # Remove any remaining ``$...$`` math-mode wrap → contents inline
    s = _LATEX_DOLLAR_DISPLAY.sub(r"\1", s)
    # Drop stray underscores that were guarding numeric subscripts
    # (e.g. ``H_3S`` → ``H3S``). Stripping ``{}`` and unmatched ``$``
    # cleans up edge cases the regex pair above doesn't catch — e.g.
    # ``$Nb/Cu40Ni60`` (leading dollar with no closer) or
    # ``Na0.31CoO2\cdot$1.3H2O`` (embedded unmatched dollar).
    return (s.replace("_", "")
              .replace("{", "")
              .replace("}", "")
              .replace("$", "")
              .strip())


# Garbage review-reason markers, sourced from the validator's own
# constants (kept in lockstep automatically) plus the api/main.py
# periodic-audit tag. A row already wearing one of these was flagged
# garbage by an earlier gate; if a sweep can no longer regenerate it,
# it is safe to soft-retire.
_GARBAGE_REVIEW_REASONS = (
    _formula_validator.DESCRIPTIVE_WORD,
    _formula_validator.CONDITION_DESCRIPTOR,
    _formula_validator.INVALID_START,
    _formula_validator.SYSTEM_DESIGNATOR,
    _formula_validator.PHASE_PREFIX,
    _formula_validator.INCOMPLETE_FORMULA,
    _formula_validator.ENGLISH_ELEMENT_NAME,
    _formula_validator.LITERAL_PLACEHOLDER,
    _formula_validator.SINGLE_ELEMENT,
    _formula_validator.CONCATENATED_PROSE,
    _formula_validator.TRADE_NAME,
    _formula_validator.GENERIC_FAMILY_NAME,
    _formula_validator.FORBIDDEN_CHAR,
    "ner_extracted_descriptive_text",
)


def _is_purgeable_orphan(
    formula: str | None,
    review_reason: str | None,
    mat_id: str,
) -> bool:
    """True iff a row this sweep did NOT regenerate is positively-
    identified NER garbage that is safe to soft-retire.

    Deliberately conservative — an absent NER source is the *normal*
    state for two large, legitimate populations that must be PRESERVED:

      * NIMS-imported rows (``nims:`` id) — no arXiv paper ever backed
        them, so a papers-only sweep can never reproduce them.
      * Valid-formula rows transiently source-less this sweep (e.g. a
        paper whose ``materials_extracted`` was just rewritten by the
        in-flight NER re-run).

    We retire ONLY rows that fail the current formula validator or were
    already tagged with a garbage reason by an earlier gate. Soft
    (needs_review=True), never DELETE — fully reversible.
    """
    if mat_id.startswith("nims:"):
        return False
    rr = review_reason or ""
    if any(g and g in rr for g in _GARBAGE_REVIEW_REASONS):
        return True
    ok, _ = _formula_validator.validate_formula(
        _formula_validator.normalize_whitespace(formula or "")
    )
    return not ok


def _material_upsert_statement(
    mat_id: str, summary: dict[str, Any], *, preserve_identity: bool = False,
):
    """Keep governance holds sticky while refreshing rebuildable summaries."""
    stmt = pg_insert(materials_table).values(id=mat_id, status="active_research", **summary)
    update_cols = {key: stmt.excluded[key] for key in summary}
    if preserve_identity:
        for key in ("formula", "formula_normalized", "family", "formula_substrate", "formula_overlayer"):
            update_cols.pop(key, None)
    mt = materials_table.c
    # Neither fresh numeric heterogeneity nor absence of an extraction is an
    # adjudication of a historical dispute. Clearing it needs a review action.
    update_cols["disputed"] = case((mt.disputed.is_(True), True), else_=stmt.excluded["disputed"])
    existing_hold = mt.needs_review.is_(True) | func.lower(func.ltrim(mt.review_reason)).like(
        "provenance_quarantine%",
    )
    update_cols["needs_review"] = case(
        (existing_hold, True),
        (stmt.excluded.needs_review.is_(True), True),
        (mt.admin_decision.isnot(None), mt.needs_review), else_=stmt.excluded["needs_review"],
    )
    update_cols["review_reason"] = case(
        # All existing holds require explicit revision review to clear, not
        # merely a new extraction snapshot. A historical positive decision
        # cannot mask a new source/anomaly hold. Decisions remain history.
        (existing_hold, mt.review_reason),
        (stmt.excluded.needs_review.is_(True), stmt.excluded.review_reason),
        (mt.admin_decision.isnot(None), mt.review_reason), else_=stmt.excluded["review_reason"],
    )
    # Repeated snapshots converge without advancing a watermark on a no-op.
    # Actual changes must advance it so dependent projections can invalidate.
    changed = or_(*(mt[key].is_distinct_from(value) for key, value in update_cols.items()))
    update_cols["updated_at"] = func.now()
    return stmt.on_conflict_do_update(index_elements=[mt.id], set_=update_cols, where=changed)


async def aggregate_from_papers() -> int:
    """Sweep papers.materials_extracted → upsert into materials.

    Returns the number of material rows upserted.
    """
    Session = _session_factory()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Track the most common display-form for each canonical key so the
    # ``formula`` column shows a sensible raw string to users. Counter
    # of raw → occurrences; we pick most_common(1) at write time.
    display_counts: dict[str, Counter[str]] = defaultdict(Counter)

    async with Session() as db:
        # -----------------------------------------------------------
        # R2.2 INTERLOCK — refuse to run unless the materials table
        # has been reconciled to the current canonicalisation scheme.
        # Re-keying rows under a changed normalize_formula WITHOUT
        # first running scripts/r22_consolidate.py --apply orphans the
        # old rows (valid formula -> reconcile preserves them) and
        # multiplies duplicates. The consolidation bumps
        # pipeline_state.materials_normalize_version on success.
        # -----------------------------------------------------------
        _vr = (await db.execute(
            select(pipeline_state_table.c.value).where(
                pipeline_state_table.c.key == "materials_normalize_version"
            )
        )).first()
        _db_ver = (int(_vr[0]) if _vr and str(_vr[0]).isdigit() else 0)
        if _db_ver < NORMALIZE_SCHEMA_VERSION:
            msg = (
                f"ABORT aggregate_from_papers: "
                f"materials_normalize_version={_db_ver} < code "
                f"NORMALIZE_SCHEMA_VERSION={NORMALIZE_SCHEMA_VERSION}. "
                f"materials is NOT consolidated to the R2.1 id scheme; "
                f"running now would orphan ~re-keyed rows and multiply "
                f"duplicates. Run scripts/r22_consolidate.py --apply "
                f"(it reconciles the table and bumps the version), "
                f"then retry."
            )
            log.critical(msg)
            raise RuntimeError(msg)

        # -----------------------------------------------------------
        # P0: Load override / refuted caches once per run
        # -----------------------------------------------------------
        override_map = await _load_all_overrides(db)
        refuted_map = await _load_all_refuted(db)
        log.info(
            "aggregator: loaded %d override entries, %d refuted entries",
            sum(len(v) for v in override_map.values()), len(refuted_map),
        )
        legacy_fields = ("pairing_symmetry", "is_unconventional", "has_competing_order", "disputed")
        legacy_rows = (await db.execute(select(
            materials_table.c.id, *(materials_table.c[name] for name in legacy_fields),
            materials_table.c.records,
        ))).all()
        legacy_by_id = {row[0]: dict(zip(legacy_fields, row[1:])) for row in legacy_rows}
        retained_by_id = {
            row[0]: row[1 + len(legacy_fields)]
            for row in legacy_rows if len(row) > 1 + len(legacy_fields)
        }

        # Stream all papers with their extracted materials. Each paper
        # is small (materials_extracted is a short list) so we can pull
        # them all at once rather than page.
        #
        # Load all statuses to distinguish positive lifecycle holds from
        # absent extractions. Held sources are skipped below; their current
        # NER records are never reintroduced by this sweep. Previously stored
        # only-source material records remain recoverable in Archive.
        #
        # credibility_tier is loaded so we can apply tier-based
        # confidence scaling (T4/T5 records get downweighted).
        stmt = select(
            papers_table.c.id,
            papers_table.c.source,
            papers_table.c.date_submitted,
            papers_table.c.date_published,
            papers_table.c.materials_extracted,
            papers_table.c.credibility_tier,
            papers_table.c.status,
        ).order_by(papers_table.c.id)
        rows = (await db.execute(stmt)).all()
        source_statuses = {row[0]: row[-1] for row in rows}
        log.info("aggregator: scanning %d papers", len(rows))

        # Credibility tier → confidence multiplier. T4/T5 papers are
        # completely excluded from aggregation: T4 are large reviews or
        # high-anomaly sources whose NER records pollute materials with
        # cited/erroneous values; T5 are retracted or refuted.
        # T3 papers (unfocused, low-confidence, or no extractions) get
        # a mild 0.8× downweight so focused experimental papers (T1/T2)
        # dominate the aggregated summary.
        _TIER_MULTIPLIER = {
            "T1": 1.0,
            "T2": 1.0,
            "T3": 0.8,
            "T4": 0.0,
            "T5": 0.0,
        }

        n_skipped_t4t5 = 0
        for paper_id, source, date_submitted, date_published, mats, cred_tier, _paper_status in rows:
            if _source_is_held(_paper_status):
                continue
            if not isinstance(mats, list) or not mats:
                continue
            effective_tier = (
                "T1" if source == "aps" or str(paper_id).startswith("aps:") else cred_tier
            )
            tier_mult = _TIER_MULTIPLIER.get(effective_tier, 1.0)
            if tier_mult <= 0.0:
                n_skipped_t4t5 += 1
                continue
            paper_date = date_submitted or date_published
            year = paper_date.year if paper_date else None
            for m in mats:
                if not isinstance(m, dict):
                    continue
                raw = m.get("formula")
                if not raw or not isinstance(raw, str):
                    continue
                # Whitespace-normalize first — NER occasionally emits
                # ``Ba 2 Cu 3 O 7`` style strings.
                raw = _formula_validator.normalize_whitespace(raw)
                # Defense-in-depth: even though the NER post-process
                # validates, legacy ``papers.materials_extracted`` rows
                # may carry pre-validator descriptive strings. Skip
                # them so they never reach materials.records.
                ok, reject_reason = _formula_validator.validate_formula(raw)
                if not ok:
                    log.debug(
                        "aggregator: skip paper=%s formula=%r reason=%s",
                        paper_id, m.get("formula"), reject_reason,
                    )
                    continue
                # Skip records the NER marked as citations of prior work
                # (introduction surveys, comparison tables, "previously
                # reported" mentions). Absent evidence_type is treated as
                # primary for backward compatibility with legacy records;
                # the P0 flag migration (alembic 0012) already hides the
                # worst legacy citation-conflation victims.
                if m.get("evidence_type") == "cited":
                    continue
                conf = m.get("confidence")
                if isinstance(conf, (int, float)) and conf < _MIN_CONFIDENCE:
                    continue
                # Numeric anomalies stay recoverable. The property-specific
                # versioned review below excludes values, not source records.
                norm = normalize_formula(raw)
                if not norm:
                    continue
                # Stamp provenance onto the record so the UI can link
                # back to the source paper and show per-paper values.
                record = dict(m)
                record["paper_id"] = paper_id
                record["credibility_tier"] = effective_tier
                # Apply credibility tier multiplier to record confidence.
                # T3 papers get 0.7× weight, T4 get 0.3×. This makes the
                # weighted-mode aggregation prefer focused experimental
                # papers (T1/T2) over reviews and low-quality sources.
                if tier_mult < 1.0:
                    raw_conf = record.get("confidence", _DEFAULT_CONFIDENCE)
                    record["confidence"] = round(raw_conf * tier_mult, 3)
                if year is not None and "year" not in record:
                    record["year"] = year
                grouped[norm].append(record)
                # Display-form bookkeeping: clean LaTeX scaffolding off
                # each candidate before counting so $-wrapped variants
                # don't compete with their already-clean siblings as
                # different "spellings". Final pick is the most-common
                # cleaned form, breaking ties by length.
                display_counts[norm][_clean_display(raw) or raw.strip()] += 1

        log.info(
            "aggregator: %d unique canonical formulas from NER "
            "(skipped %d T4/T5 papers)",
            len(grouped), n_skipped_t4t5,
        )

        upserted = 0
        for norm, records in grouped.items():
            # Most-common raw spelling — or shortest if frequencies tie,
            # since shorter usually means less LaTeX noise.
            candidates = display_counts[norm].most_common()
            top_count = candidates[0][1]
            top_raws = [r for r, c in candidates if c == top_count]
            display_raw = min(top_raws, key=len)
            mat_id = _material_id(norm)
            retained = retained_by_id.get(mat_id)
            if isinstance(retained, list):
                # Preserve the existing Archive audit path for a mixed-source
                # material. Do not import new held extractions or reconstruct
                # records missing from historical material rows. Current
                # summaries below use only the independently eligible pool.
                # SC07 may conservatively keep the whole material on hold
                # until a result-scoped admission workflow is implemented.
                records = records + [record for record in retained
                    if isinstance(record, dict)
                    and _record_source_is_held(record, source_statuses)]

            summary = _derive_summary(
                display_raw, records,
                overrides=override_map.get(norm),
                refuted=refuted_map.get(norm),
                source_statuses=source_statuses,
                legacy_summary=legacy_by_id.get(_material_id(norm)),
            )
            await db.execute(_material_upsert_statement(mat_id, summary))
            upserted += 1
            if upserted % 200 == 0:
                await db.commit()
                log.info("  upserted %d/%d materials…",
                         upserted, len(grouped))

        await db.commit()
        log.info("aggregator: %d materials upserted", upserted)

        # -----------------------------------------------------------
        # P2: Parent-variant linking
        # -----------------------------------------------------------
        # For each canonical formula, compute its parent key. If the
        # parent key differs from the formula itself AND the parent
        # exists in the DB, set parent_material_id.
        parent_links = 0
        variant_counts: dict[str, int] = defaultdict(int)
        all_norms = set(grouped.keys())

        for norm in all_norms:
            parent_key = _parent_formula_key(norm)
            if parent_key == norm:
                continue  # this IS a parent, not a variant
            parent_id = _material_id(parent_key)
            child_id = _material_id(norm)
            # Only link if the parent actually exists
            if parent_key in all_norms:
                await db.execute(
                    materials_table.update()
                    .where(materials_table.c.id == child_id)
                    .values(parent_material_id=parent_id)
                )
                variant_counts[parent_key] += 1
                parent_links += 1

        # Update variant_count on parent rows
        for parent_norm, count in variant_counts.items():
            pid = _material_id(parent_norm)
            await db.execute(
                materials_table.update()
                .where(materials_table.c.id == pid)
                .values(variant_count=count)
            )

        await db.commit()
        log.info(
            "aggregator: linked %d variants to %d parents",
            parent_links, len(variant_counts),
        )

        # -----------------------------------------------------------
        # P3: Discriminating orphan reconcile
        # -----------------------------------------------------------
        # Rows in `materials` that this sweep did NOT regenerate are
        # "orphans". The upsert path only ever inserts/updates present
        # canonicals and never deletes, so stale pre-validator NER
        # garbage from a looser era lingers visibly forever. Soft-retire
        # ONLY positively-identified garbage (see _is_purgeable_orphan) or
        # a material whose every stored record has an explicit current source
        # hold. NIMS-only and temporarily source-less rows are preserved.
        # Historical manual decisions cannot authorize stale source support.
        live_ids = {_material_id(n) for n in all_norms}
        candidates = (await db.execute(
            select(
                materials_table.c.id,
                materials_table.c.formula,
                materials_table.c.review_reason,
                materials_table.c.records,
                materials_table.c.needs_review,
                materials_table.c.admin_decision,
            )
        )).all()
        retired = 0
        source_held = 0
        for oid, oformula, orr, old_records, old_needs_review, old_decision in candidates:
            if oid in live_ids:
                continue
            if not oid.startswith("nims:") and _only_held_source_support(old_records, source_statuses):
                summary = _derive_summary(
                    oformula, old_records,
                    source_statuses=source_statuses,
                    legacy_summary=legacy_by_id.get(oid),
                )
                if old_needs_review and orr:
                    # A source hold is additional information, not permission
                    # to erase an unrelated pre-existing provenance hold.
                    summary["review_reason"] = orr
                # Preserve the existing ID, records, independent governance
                # flags and manual decision; only the derived view changes.
                await db.execute(_material_upsert_statement(oid, summary, preserve_identity=True))
                source_held += 1
                continue
            if old_needs_review or old_decision is not None:
                continue
            if not _is_purgeable_orphan(oformula, orr, oid):
                continue
            await db.execute(
                materials_table.update()
                .where(materials_table.c.id == oid)
                .values(
                    needs_review=True,
                    review_reason=_clip(
                        "review_reason",
                        f"orphaned_invalid_source; was: {orr or '(none)'}",
                    ),
                )
            )
            retired += 1
            if retired % 200 == 0:
                await db.commit()
        await db.commit()
        log.info(
            "aggregator: soft-retired %d stale orphan rows "
            "(scanned %d existing materials, %d live this sweep)",
            retired, len(candidates), len(live_ids),
        )
        log.info("aggregator: refreshed %d only-source held material views", source_held)

    return upserted
