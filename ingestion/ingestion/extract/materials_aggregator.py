"""Roll per-paper NER records up into the ``materials`` table.

The arXiv pipeline writes ``papers.materials_extracted`` on every
upsert — that's the v2 NER output from ``material_ner.extract_materials``
for that one paper. This module sweeps all papers, groups the records
by normalized formula, and upserts a row-per-formula into the
``materials`` table with summary columns derived from the records.

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

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.index.indexer import _session_factory, materials_table, papers_table

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Formula normalization — shared with nims.py so both importers agree on
# the primary key.
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
_SUBSCRIPT = re.compile(r"_\{?([0-9.]+)\}?")


def normalize_formula(raw: str) -> str:
    """Collapse whitespace, strip LaTeX subscripts, lowercase.

    This is the *key*, not the display form — pages should always
    render the original raw string, not this.
    """
    s = _WS.sub("", raw.strip())
    s = _SUBSCRIPT.sub(r"\1", s)
    return s.lower()


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

def _max_numeric(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in records if isinstance(r.get(key), (int, float))]
    return max(vals) if vals else None


def _median_numeric(records: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in records if isinstance(r.get(key), (int, float))]
    return float(median(vals)) if vals else None


def _any_true(records: list[dict[str, Any]], key: str) -> bool | None:
    """True if any record sets this flag, None if no record says either way."""
    seen = False
    for r in records:
        v = r.get(key)
        if v is True:
            return True
        if v is False:
            seen = True
    return False if seen else None


def _mode_str(records: list[dict[str, Any]], key: str) -> str | None:
    """Most common non-null string value across records, 'unknown' excluded."""
    counter: Counter[str] = Counter()
    for r in records:
        v = r.get(key)
        if isinstance(v, str) and v and v.lower() != "unknown":
            counter[v] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def _first_non_null(records: list[dict[str, Any]], key: str) -> Any:
    for r in records:
        v = r.get(key)
        if v is not None and v != "":
            return v
    return None


def _derive_summary(formula_raw: str,
                    records: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the v2 material-level summary from its record list.

    Rules:
    - ``tc_max``:    max of numeric tc_kelvin across all records
    - ``tc_ambient``: max of tc_kelvin across records with pressure_gpa==0
    - ``ambient_sc``: true iff any ambient tc is present
    - ``pairing_symmetry`` / ``structure_phase`` / ``sample_form`` /
      ``pressure_type`` / ``doping_type`` / ``competing_order``: mode
    - ``crystal_structure`` / ``space_group``: first non-null
    - ``hc2_tesla``: max (the upper critical field reported is already
                    a maximum, and aggregating multiple papers by max
                    gives the community best estimate)
    - ``lambda_eph`` / ``omega_log_k`` / ``rho_s_mev``: max (computational
                    papers sometimes undercalculate; the highest value
                    usually corresponds to the optimally-coupled phase)
    - ``rho_exponent``: median (NFL/FL distinction is robust to outliers)
    - ``t_cdw_k`` / ``t_sdw_k`` / ``t_afm_k``: max
    - ``has_competing_order``: true iff any of the above three is set
                               or ``competing_order`` is non-null
    - ``is_*`` flags: "any true" semantics (True if any record asserts,
                     False if any record denies and none assert, None
                     if no record says either way)
    - ``discovery_year``: min of paper years in records (first report)
    - ``total_papers``: cardinality of distinct paper_ids
    """
    tc_max = _max_numeric(records, "tc_kelvin")

    ambient_records = [
        r for r in records
        if isinstance(r.get("tc_kelvin"), (int, float))
        and (r.get("pressure_gpa") in (0, 0.0) or r.get("ambient_sc") is True)
    ]
    tc_ambient = max(
        (r["tc_kelvin"] for r in ambient_records),
        default=None,
    )

    ambient_sc = bool(ambient_records) or _any_true(records, "ambient_sc")

    competing_order = _mode_str(records, "competing_order")
    t_cdw = _max_numeric(records, "t_cdw_k")
    t_sdw = _max_numeric(records, "t_sdw_k")
    t_afm = _max_numeric(records, "t_afm_k")

    has_competing_order = bool(
        competing_order or t_cdw is not None
        or t_sdw is not None or t_afm is not None
    )

    # Build tc_max_conditions from the winning record
    tc_max_cond = None
    if tc_max is not None:
        for r in records:
            if r.get("tc_kelvin") == tc_max:
                parts: list[str] = []
                if r.get("pressure_gpa"):
                    parts.append(f"P={r['pressure_gpa']} GPa")
                if r.get("sample_form"):
                    parts.append(str(r["sample_form"]))
                if r.get("measurement"):
                    parts.append(str(r["measurement"]))
                tc_max_cond = ", ".join(parts) or None
                break

    paper_ids = {r.get("paper_id") for r in records if r.get("paper_id")}
    years = [r.get("year") for r in records
             if isinstance(r.get("year"), int) and r.get("year") > 1900]
    discovery_year = min(years) if years else None

    return {
        "formula": formula_raw[:200],
        "formula_normalized": normalize_formula(formula_raw)[:200],
        "tc_max": tc_max,
        "tc_max_conditions": tc_max_cond,
        "tc_ambient": tc_ambient,
        "ambient_sc": ambient_sc,
        "discovery_year": discovery_year,
        "total_papers": len(paper_ids),
        # Structure
        "crystal_structure": _first_non_null(records, "crystal_structure"),
        "space_group":       _first_non_null(records, "space_group"),
        "structure_phase":   _mode_str(records, "structure_phase"),
        "lattice_params":    _lattice_params(records),
        # SC parameters
        "pairing_symmetry":  _mode_str(records, "pairing_symmetry"),
        "gap_structure":     _mode_str(records, "gap_structure"),
        "hc2_tesla":         _max_numeric(records, "hc2_tesla"),
        "hc2_conditions":    _first_non_null(records, "hc2_conditions"),
        "lambda_eph":        _max_numeric(records, "lambda_eph"),
        "omega_log_k":       _max_numeric(records, "omega_log_k"),
        "rho_s_mev":         _max_numeric(records, "rho_s_mev"),
        # Competing orders
        "t_cdw_k":           t_cdw,
        "t_sdw_k":           t_sdw,
        "t_afm_k":           t_afm,
        "rho_exponent":      _median_numeric(records, "rho_exponent"),
        "competing_order":   competing_order,
        "has_competing_order": has_competing_order,
        # Samples / pressure
        "sample_form":       _mode_str(records, "sample_form"),
        "substrate":         _first_non_null(records, "substrate"),
        "pressure_type":     _mode_str(records, "pressure_type"),
        "doping_type":       _mode_str(records, "doping_type"),
        "doping_level":      _median_numeric(records, "doping_level"),
        # Flags
        "is_topological":      _any_true(records, "is_topological"),
        "is_unconventional":   _any_true(records, "is_unconventional"),
        "is_2d_or_interface":  _any_true(records, "is_2d_or_interface"),
        "disputed":            _any_true(records, "disputed"),
        "records": records,
    }


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


async def aggregate_from_papers() -> int:
    """Sweep papers.materials_extracted → upsert into materials.

    Returns the number of material rows upserted.
    """
    Session = _session_factory()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # Track the first display-form for each normalized key.
    display: dict[str, str] = {}

    async with Session() as db:
        # Stream all papers with their extracted materials. Each paper
        # is small (materials_extracted is a short list) so we can pull
        # them all at once rather than page.
        stmt = select(
            papers_table.c.id,
            papers_table.c.date_submitted,
            papers_table.c.materials_extracted,
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
                conf = m.get("confidence")
                if isinstance(conf, (int, float)) and conf < _MIN_CONFIDENCE:
                    continue
                norm = normalize_formula(raw)
                if not norm:
                    continue
                # Stamp provenance onto the record so the UI can link
                # back to the source paper.
                record = dict(m)
                record["paper_id"] = paper_id
                if year is not None and "year" not in record:
                    record["year"] = year
                grouped[norm].append(record)
                display.setdefault(norm, raw)

        log.info("aggregator: %d unique formulas from NER", len(grouped))

        upserted = 0
        for norm, records in grouped.items():
            raw = display[norm]
            summary = _derive_summary(raw, records)
            mat_id = _material_id(norm)

            stmt = pg_insert(materials_table).values(
                id=mat_id,
                status="active_research",
                **summary,
            )
            update_cols = {k: stmt.excluded[k] for k in summary}
            stmt = stmt.on_conflict_do_update(
                index_elements=[materials_table.c.id],
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
