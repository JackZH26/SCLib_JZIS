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

2. **Confidence-weighted MODE** for discrete fields (pairing,
   structure_phase, …). A single high-confidence paper beats two
   hedged mentions; ties below a 60% share threshold fall back to
   NULL. Keeps disputed / weak signals out of the flat columns.

3. **Dual-threshold boolean consensus** (0.7 for / 0.2 against) for
   ``is_topological`` & peers. Without this, every material that a
   single paper labelled ``False`` (common NER default) showed up as
   "confirmed non-topological", which is dishonest.

4. **Cross-family phase sanity check** — drops ``cuprate_*`` when the
   formula has no Cu (Gemini over-applies the cuprate taxonomy to
   unfamiliar compounds like MgB₂ or bismuthates).

5. **Family fallback** — when NER doesn't emit a ``family`` for a
   material, fall back to the rule-based ``classify_family`` shared
   with the NIMS importer.

6. **Numeric dispute detection** — when two+ ambient-pressure papers
   disagree on Tc by >30%, flag ``disputed=True``.

The aggregator is idempotent and safe to re-run: every call rebuilds
the summary from scratch. We also merge NER records with any records
already present on the material (e.g. NIMS imports) so the two
ingestion paths coexist.

Invoked by:
  sclib-ingest --mode aggregate-materials

Typical cadence: once per daily cron run, after the incremental arXiv
harvest has finished writing ``papers.materials_extracted``.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from statistics import median
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.index.indexer import (
    _session_factory,
    manual_overrides_table,
    materials_table,
    papers_table,
    refuted_claims_table,
)
# Canonicalization + family rules live in nims.py and are shared so
# both import paths (NIMS CSV + arXiv NER) agree on the grouping key.
from ingestion.extract import formula_validator as _formula_validator
from ingestion.nims import classify_family as _classify_family
from ingestion.nims import infer_unconventional as _infer_unconventional
from ingestion.nims import normalize_formula

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
# Ambient-pressure Tc spread threshold above which we flag the material
# as "disputed" — 30% means one paper reports 100 K, another 65 K.
_TC_DISPUTE_THRESHOLD = 0.30

# Physically implausible Tc. Confirmed ambient-pressure SC Tc tops out
# at ~140 K (cuprates); even 200 GPa hydrides stay under 260 K. Any
# record above this at ambient pressure is almost certainly an NER
# confusion with Curie / melting / mechanical transitions. We flag
# those materials ``needs_review=True`` and the API hides them by
# default (?include_pending=true surfaces them for admin review).
_TC_SANITY_MAX_K = 250.0

# Numeric fields subject to float32 artifact rounding (Step 0.6 / C4).
_NUMERIC_FIELDS = (
    "tc_max", "tc_ambient", "pressure_gpa", "hc2_tesla",
    "lambda_london_nm", "xi_gl_nm", "lambda_eph", "omega_log_k",
    "rho_s_mev", "t_cdw_k", "t_sdw_k", "t_afm_k", "rho_exponent",
    "doping_level",
)


# ---------------------------------------------------------------------------
# P0: Override / refuted-claim infrastructure
# ---------------------------------------------------------------------------

class _OverrideEntry:
    """In-memory representation of one manual_overrides row."""
    __slots__ = ("field", "value_str", "is_cap", "source", "reason")

    def __init__(self, field: str, value_str: str, is_cap: bool,
                 source: str, reason: str | None):
        self.field = field
        self.value_str = value_str
        self.is_cap = is_cap
        self.source = source
        self.reason = reason

    @property
    def numeric_value(self) -> float | None:
        try:
            return float(self.value_str)
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
            manual_overrides_table.c.canonical,
            manual_overrides_table.c.field,
            manual_overrides_table.c.override_value,
            manual_overrides_table.c.is_cap,
            manual_overrides_table.c.source,
            manual_overrides_table.c.reason,
        )
    )).all()
    for canonical, field, value, is_cap, source, reason in rows:
        result[canonical].append(
            _OverrideEntry(field, value, is_cap, source, reason)
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
    """Apply manual overrides to a computed summary dict.

    Returns a list of human-readable notes describing what was changed,
    for appending to review_reason.
    """
    notes: list[str] = []

    # Group overrides by field: exact overrides take priority over caps
    by_field: dict[str, list[_OverrideEntry]] = defaultdict(list)
    for ov in overrides:
        by_field[ov.field].append(ov)

    for field, entries in by_field.items():
        # Exact overrides (is_cap=False) first
        exact = [e for e in entries if not e.is_cap]
        caps = [e for e in entries if e.is_cap]

        if exact:
            ov = exact[0]  # take the first exact override
            if field in ("pairing_symmetry", "gap_structure",
                         "competing_order", "crystal_structure",
                         "space_group", "structure_phase"):
                old = summary.get(field)
                summary[field] = ov.string_value
                notes.append(f"{field}: {old!r} -> {ov.string_value!r} (override: {ov.source})")
            else:
                val = ov.numeric_value
                if val is not None:
                    old = summary.get(field)
                    summary[field] = val
                    notes.append(f"{field}: {old} -> {val} (override: {ov.source})")
        elif caps:
            cap_entry = caps[0]
            cap_val = cap_entry.numeric_value
            if cap_val is not None:
                current = summary.get(field)
                if isinstance(current, (int, float)) and current > cap_val:
                    summary[field] = cap_val
                    notes.append(
                        f"{field}: {current} clamped to {cap_val} "
                        f"(per-compound cap: {cap_entry.source})"
                    )

    return notes


def _confidence(r: dict[str, Any]) -> float:
    """Best-effort float confidence, clamped to [0, 1]."""
    v = r.get("confidence")
    if not isinstance(v, (int, float)):
        return _DEFAULT_CONFIDENCE
    return max(0.0, min(1.0, float(v)))


def _max_numeric(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in records if isinstance(r.get(key), (int, float))]
    return max(vals) if vals else None


def _corroborated_max(
    records: list[dict[str, Any]],
    key: str,
) -> tuple[float | None, int]:
    """Highest value corroborated by multiple independent papers.

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

    Returns (value, supporting_paper_count).
    """
    per_paper: dict[str, float] = {}
    for r in records:
        v = r.get(key)
        pid = r.get("paper_id")
        if isinstance(v, (int, float)) and v > 0 and isinstance(pid, str) and pid:
            if v > per_paper.get(pid, 0):
                per_paper[pid] = float(v)
    if not per_paper:
        return None, 0

    values = sorted(per_paper.values(), reverse=True)
    n_papers = len(values)
    if n_papers < 5:
        return values[0], n_papers

    min_support = max(2, min(10, n_papers // 20))
    for cand in values:
        support = sum(1 for v in values if v >= cand)
        if support >= min_support:
            return cand, support

    # Unreachable when n_papers >= 5 (the smallest value always has
    # support = n_papers), but fall back for safety.
    return values[-1], n_papers


def _median_numeric(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in records if isinstance(r.get(key), (int, float))]
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
    "False"). A common NER failure mode is emitting ``is_topological=False``
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
    ``cuprate_*`` phase labels (e.g. MgB₂ → cuprate_123). Block that
    obvious contradiction; leave everything else alone.
    """
    if not structure_phase:
        return None
    if structure_phase.startswith("cuprate") and not _has_cu(formula_raw):
        return None
    return structure_phase


def _derive_summary(
    formula_raw: str,
    records: list[dict[str, Any]],
    *,
    overrides: list[_OverrideEntry] | None = None,
    refuted: _RefutedEntry | None = None,
) -> dict[str, Any]:
    """Build the v2 material-level summary from its record list.

    See module docstring for the rule overview; this is the
    implementation.

    P0 additions:
    - Record-level flagging (Step 0.5): individual records that fail
      sanity checks are excluded from aggregation instead of hiding
      the entire material. Only if ALL records fail does the material
      get needs_review=True.
    - Override application (Step 0.4): manual_overrides values are
      applied after natural aggregation.
    - Float rounding (Step 0.6): all numeric outputs are rounded to
      3 decimal places to eliminate float32 artifacts.
    """
    # -------------------------------------------------------------------
    # Step 0.5: Record-level flagging — exclude bad records, not the
    # whole material. Per-compound caps from manual_overrides further
    # tighten what "sane" means for well-known compounds.
    # -------------------------------------------------------------------
    per_compound_tc_cap: float | None = None
    if overrides:
        for ov in overrides:
            if ov.field == "tc_max" and ov.is_cap:
                cap_val = ov.numeric_value
                if cap_val is not None:
                    per_compound_tc_cap = cap_val
                    break

    clean_records: list[dict[str, Any]] = []
    flagged_count = 0
    for r in records:
        tc_val = r.get("tc_kelvin")
        tc_is_numeric = isinstance(tc_val, (int, float))
        # Global sanity ceiling
        if tc_is_numeric and tc_val > _TC_SANITY_MAX_K:
            flagged_count += 1
            continue
        # Per-compound cap: record exceeds known physical ceiling by >50%
        if (
            per_compound_tc_cap is not None
            and tc_is_numeric
            and tc_val > per_compound_tc_cap * 1.5
        ):
            flagged_count += 1
            continue
        clean_records.append(r)

    # If ALL records were flagged, mark the material for review.
    # Otherwise, aggregate from the clean subset only.
    all_records_bad = len(clean_records) == 0 and len(records) > 0
    if all_records_bad:
        # Fall back to original records so we still produce *something*
        # (the needs_review flag will hide it from public API).
        clean_records = records
    elif flagged_count > 0:
        log.info(
            "record-level flagging: %s — dropped %d/%d records "
            "(per-compound cap=%s)",
            formula_raw, flagged_count, len(records), per_compound_tc_cap,
        )
    records = clean_records

    # tc_max is the highest Tc reported in ANY condition (high
    # pressure, thin film, doped, …) — the scientific "record-high"
    # metric. Uses a corroboration rule (≥2 papers within 15%) to
    # reject single-paper outliers; see _corroborated_max docstring.
    tc_max, tc_max_support = _corroborated_max(records, "tc_kelvin")

    # tc_ambient is intentionally *stricter*: only records where NER
    # affirmatively emitted ``ambient_sc: true`` count. We deliberately
    # do NOT trust ``pressure_gpa == 0`` alone because the NER uses
    # 0.0 as a "value unknown" fallback. When no paper explicitly
    # confirmed ambient SC, we leave tc_ambient NULL — honest
    # "unknown" beats a wrong answer.
    ambient_records = [
        r for r in records
        if isinstance(r.get("tc_kelvin"), (int, float))
        and r.get("ambient_sc") is True
    ]
    # Apply the same corroboration rule here so an outlier
    # ambient-pressure claim doesn't dominate either.
    tc_ambient, _ = _corroborated_max(ambient_records, "tc_kelvin")

    # Invariant: tc_max >= tc_ambient (by definition, "record high
    # in any condition" cannot be below "record high at ambient").
    # The corroboration rule uses a support threshold that scales
    # with the sample size, so the stricter full-set threshold can
    # reject a value that the smaller ambient subset accepts — the
    # subset then returns a number higher than the full-set max.
    # Promote tc_max to match so the summary stays consistent.
    if (
        tc_max is not None
        and tc_ambient is not None
        and tc_ambient > tc_max
    ):
        tc_max = tc_ambient
        tc_max_support = max(tc_max_support, 1)
    # Numeric dispute: ambient-pressure Tc values from 2+ papers span
    # more than 30% of the max. Typical cause is over/under-doped
    # samples in different papers; worth surfacing to the user.
    numeric_disputed = False
    if len(ambient_records) >= 2:
        tc_vals = [r["tc_kelvin"] for r in ambient_records]
        tc_max_v = max(tc_vals)
        if tc_max_v > 0:
            spread = (tc_max_v - min(tc_vals)) / tc_max_v
            numeric_disputed = spread > _TC_DISPUTE_THRESHOLD

    # The summary flag ``ambient_sc`` follows the same strict rule:
    # true iff at least one record has ambient_sc==True AND no record
    # denies it (weighted-boolean handles the "denied by most"
    # case). Without evidence either way we return None, not False.
    ambient_sc = _weighted_boolean(records, "ambient_sc")
    # If any record directly confirmed ambient, that wins regardless
    # of how the weighted vote came out — one good observation is
    # enough to say the material has an ambient-pressure SC phase.
    if any(r.get("ambient_sc") is True for r in records):
        ambient_sc = True

    competing_order = _weighted_mode_str(records, "competing_order")
    t_cdw = _max_numeric(records, "t_cdw_k")
    t_sdw = _max_numeric(records, "t_sdw_k")
    t_afm = _max_numeric(records, "t_afm_k")

    has_competing_order = bool(
        competing_order or t_cdw is not None
        or t_sdw is not None or t_afm is not None
    )

    # tc_max_conditions: pick the record tying the max and format as
    # "P={p} GPa, <sample>, <measurement> (arXiv:<id>)". Appends a
    # corroboration note ("confirmed by N papers") so users can see
    # how well-supported the headline number is.
    tc_max_cond = None
    if tc_max is not None:
        for r in records:
            if r.get("tc_kelvin") == tc_max:
                parts: list[str] = []
                p = r.get("pressure_gpa")
                if isinstance(p, (int, float)) and p > 0:
                    parts.append(f"P={p:g} GPa")
                elif isinstance(p, (int, float)):
                    parts.append("ambient")
                if r.get("sample_form"):
                    parts.append(str(r["sample_form"]))
                if r.get("measurement") and str(r["measurement"]).lower() != "unknown":
                    parts.append(str(r["measurement"]))
                pid = r.get("paper_id")
                if pid:
                    arx = str(pid).removeprefix("arxiv:")
                    parts.append(f"arXiv:{arx}")
                tc_max_cond = ", ".join(parts) or None
                break
        if tc_max_support >= 2:
            note = f"confirmed by {tc_max_support} papers"
            tc_max_cond = (
                f"{tc_max_cond}, {note}" if tc_max_cond else note
            )

    paper_ids = {r.get("paper_id") for r in records if r.get("paper_id")}
    years = [
        r.get("year") for r in records
        if isinstance(r.get("year"), int) and r.get("year") > 1900
    ]
    discovery_year = min(years) if years else None

    # Structure phase with cross-family sanity check
    raw_phase = _weighted_mode_str(records, "structure_phase")
    structure_phase = _sanity_check_structure_phase(formula_raw, raw_phase)

    # Family: trust NER's mode first, fall back to the rule-based
    # classifier from nims.py when NER didn't say (most common case).
    family = _weighted_mode_str(records, "family") or _classify_family(formula_raw)

    # is_unconventional: trust NER weighted-boolean first; when NER is
    # silent (the common case — 61.8% missing), infer from family.
    # Family-based inference is definitive for clear-cut families
    # (cuprate → True, elemental → False) and returns None for
    # ambiguous ones (hydride, chalcogenide).
    is_unconv_ner = _weighted_boolean(records, "is_unconventional")
    is_unconventional = (
        is_unconv_ner
        if is_unconv_ner is not None
        else _infer_unconventional(family)
    )

    # disputed: union of NER-reported disputes and numeric-Tc dispute
    disputed_ner = _weighted_boolean(records, "disputed")
    disputed = bool(numeric_disputed) or bool(disputed_ner)

    # -------------------------------------------------------------------
    # Sanity gate: needs_review
    # -------------------------------------------------------------------
    # P0 change (Step 0.5): record-level flagging already excluded the
    # worst outliers above. `needs_review` is now set only when ALL
    # records failed (all_records_bad) or when the *aggregated* values
    # still exceed the ceiling after record-level filtering.
    needs_review = False
    review_reason: str | None = None
    if all_records_bad:
        needs_review = True
        review_reason = (
            f"all_{len(records)}_records_failed_sanity_checks"
        )
    elif tc_max is not None and tc_max > _TC_SANITY_MAX_K:
        needs_review = True
        review_reason = "tc_max_exceeds_250K"
    elif tc_ambient is not None and tc_ambient > _TC_SANITY_MAX_K:
        needs_review = True
        review_reason = "tc_ambient_exceeds_250K"

    # Every string going into a varchar column passes through _clip
    # so a chatty NER hallucination (e.g. "single Fe vacancy for every
    # eight Fe-sites arranged in a √10×√8 parallelogram structure"
    # being dropped into ``crystal_structure``) doesn't crash the
    # whole aggregator with a StringDataRightTruncationError. Values
    # over the column budget become NULL — better empty than wrong.
    summary = {
        "formula": formula_raw[:200],
        "formula_normalized": normalize_formula(formula_raw)[:200],
        "family":            _clip("family", family),
        "tc_max": tc_max,
        "tc_max_conditions": _clip("tc_max_conditions", tc_max_cond),
        "tc_ambient": tc_ambient,
        "ambient_sc": ambient_sc,
        "discovery_year": discovery_year,
        "total_papers": len(paper_ids),
        # Structure (earliest paper wins for structural claims)
        "crystal_structure": _clip("crystal_structure",
                                   _earliest_non_null(records, "crystal_structure")),
        "space_group":       _clip("space_group",
                                   _earliest_non_null(records, "space_group")),
        "structure_phase":   _clip("structure_phase", structure_phase),
        "lattice_params":    _lattice_params(records),
        # SC parameters (discrete → weighted mode, scalar → max)
        "pairing_symmetry":  _clip("pairing_symmetry",
                                   _weighted_mode_str(records, "pairing_symmetry")),
        "gap_structure":     _clip("gap_structure",
                                   _weighted_mode_str(records, "gap_structure")),
        "hc2_tesla":         _max_numeric(records, "hc2_tesla"),
        "hc2_conditions":    _clip("hc2_conditions",
                                   _first_non_null(records, "hc2_conditions")),
        "lambda_eph":        _max_numeric(records, "lambda_eph"),
        "omega_log_k":       _max_numeric(records, "omega_log_k"),
        "rho_s_mev":         _max_numeric(records, "rho_s_mev"),
        # Competing orders
        "t_cdw_k":           t_cdw,
        "t_sdw_k":           t_sdw,
        "t_afm_k":           t_afm,
        "rho_exponent":      _median_numeric(records, "rho_exponent"),
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
        "doping_level":      _median_numeric(records, "doping_level"),
        # Flags (weighted-boolean → None when weak / disputed)
        "is_topological":      _weighted_boolean(records, "is_topological"),
        "is_unconventional":   is_unconventional,
        "is_2d_or_interface":  _weighted_boolean(records, "is_2d_or_interface"),
        "disputed":            disputed,
        # Automatic sanity gate
        "needs_review":        needs_review,
        "review_reason":       _clip("review_reason", review_reason),
        "records": records,
    }

    # -------------------------------------------------------------------
    # Step 0.4: Apply manual overrides (exact replacements + caps)
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

    # -------------------------------------------------------------------
    # Step 0.6: Round all numeric fields to 3 decimals (float32 fix)
    # -------------------------------------------------------------------
    for key in _NUMERIC_FIELDS:
        val = summary.get(key)
        if isinstance(val, float):
            summary[key] = round(val, 3)

    return summary


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
        # P0: Load override / refuted caches once per run
        # -----------------------------------------------------------
        override_map = await _load_all_overrides(db)
        refuted_map = await _load_all_refuted(db)
        log.info(
            "aggregator: loaded %d override entries, %d refuted entries",
            sum(len(v) for v in override_map.values()), len(refuted_map),
        )

        # Stream all papers with their extracted materials. Each paper
        # is small (materials_extracted is a short list) so we can pull
        # them all at once rather than page.
        #
        # Retracted papers are excluded so their fabricated / flagged
        # claims do not re-pollute materials.records on every aggregator
        # run. This is what makes the alembic 0010 Schön-fraud cleanup
        # *durable* — without this filter, the retracted papers would
        # stay in papers.materials_extracted and get re-aggregated here.
        stmt = select(
            papers_table.c.id,
            papers_table.c.date_submitted,
            papers_table.c.materials_extracted,
        ).where(
            (papers_table.c.status != "retracted")
            | (papers_table.c.status.is_(None))
        )
        rows = (await db.execute(stmt)).all()
        log.info("aggregator: scanning %d papers", len(rows))

        for paper_id, date_submitted, mats in rows:
            if not isinstance(mats, list) or not mats:
                continue
            year = date_submitted.year if date_submitted else None
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
                # Numeric sanity: tc_kelvin must land in a Postgres-safe
                # double range AND be physically meaningful. The NER
                # occasionally hallucinates 1e-100 K ("essentially zero")
                # for placeholder materials; that triggers asyncpg's
                # NumericValueOutOfRangeError on the float column. Drop
                # records with tc_kelvin outside (0.01, 300) — the
                # confidence=0.3 floor in NER post-processing should
                # have caught these but it's a soft bound, not enforced.
                tc = m.get("tc_kelvin")
                if isinstance(tc, (int, float)) and (tc < 0.01 or tc > 300):
                    continue
                norm = normalize_formula(raw)
                if not norm:
                    continue
                # Stamp provenance onto the record so the UI can link
                # back to the source paper and show per-paper values.
                record = dict(m)
                record["paper_id"] = paper_id
                if year is not None and "year" not in record:
                    record["year"] = year
                grouped[norm].append(record)
                # Display-form bookkeeping: clean LaTeX scaffolding off
                # each candidate before counting so $-wrapped variants
                # don't compete with their already-clean siblings as
                # different "spellings". Final pick is the most-common
                # cleaned form, breaking ties by length.
                display_counts[norm][_clean_display(raw) or raw.strip()] += 1

        log.info("aggregator: %d unique canonical formulas from NER",
                 len(grouped))

        upserted = 0
        for norm, records in grouped.items():
            # Most-common raw spelling — or shortest if frequencies tie,
            # since shorter usually means less LaTeX noise.
            candidates = display_counts[norm].most_common()
            top_count = candidates[0][1]
            top_raws = [r for r, c in candidates if c == top_count]
            display_raw = min(top_raws, key=len)

            summary = _derive_summary(
                display_raw, records,
                overrides=override_map.get(norm),
                refuted=refuted_map.get(norm),
            )
            mat_id = _material_id(norm)

            stmt = pg_insert(materials_table).values(
                id=mat_id,
                status="active_research",
                **summary,
            )
            update_cols = {k: stmt.excluded[k] for k in summary}
            # Preserve admin review decisions: when admin_decision is
            # set (admin already reviewed this material), keep the
            # existing needs_review + review_reason values so automated
            # re-aggregation can't undo manual approvals/confirmations.
            mt = materials_table.c
            update_cols["needs_review"] = case(
                (mt.admin_decision.isnot(None), mt.needs_review),
                else_=stmt.excluded["needs_review"],
            )
            update_cols["review_reason"] = case(
                (mt.admin_decision.isnot(None), mt.review_reason),
                else_=stmt.excluded["review_reason"],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[mt.id],
                set_=update_cols,
            )
            await db.execute(stmt)
            upserted += 1
            if upserted % 200 == 0:
                await db.commit()
                log.info("  upserted %d/%d materials…",
                         upserted, len(grouped))

        await db.commit()
    log.info("aggregator: %d materials upserted", upserted)
    return upserted
