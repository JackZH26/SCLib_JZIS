"""NIMS SuperCon CSV → Postgres ``materials`` loader.

NIMS publishes one row per *measurement* (a formula + Tc + conditions).
Our aggregated ``materials`` table keeps one row per unique normalized
formula, with a JSONB ``records`` list holding every measurement and a
``tc_max`` summary column for cheap list/filter queries.

Usage::

    docker compose run --rm ingestion \\
        sclib-import-nims --csv /data/supercon.csv [--limit 5000] [--dry-run]

The importer is deliberately tolerant about column names because the
NIMS release format has drifted over the years. We accept a small set of
aliases for each field and emit a warning if we can't find one.

Family classification is heuristic. This runs once per import, never at
query time, so the cost of being wrong is low — operators can re-run
with a fresh CSV.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from ingestion.index.indexer import _session_factory, materials_table

log = logging.getLogger("sclib.nims")


# ---------------------------------------------------------------------------
# CSV column discovery
# ---------------------------------------------------------------------------

# Maps logical field → list of accepted column headers (case-insensitive,
# whitespace-trimmed). First hit wins.
COLUMN_ALIASES: dict[str, list[str]] = {
    "formula": ["formula", "name", "element", "composition", "chemical_formula"],
    "tc": ["tc", "tc (k)", "tc_k", "tc_onset", "tconset", "t_c",
           "criticaltemperature", "criticaltemperature(k)"],
    "structure": ["structure", "crystal_structure", "spacegroup", "space_group"],
    "pressure": ["pressure", "pressure_gpa", "p (gpa)", "p_gpa"],
    "doping": ["doping", "doping_level", "x", "composition_x"],
    "reference": ["reference", "doi", "ref", "citation"],
}


def _find_col(headers: list[str], logical: str) -> str | None:
    normalized = {h.strip().lower(): h for h in headers}
    for alias in COLUMN_ALIASES[logical]:
        if alias in normalized:
            return normalized[alias]
    return None


# ---------------------------------------------------------------------------
# Formula normalization
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")
# LaTeX brace subscripts: ``_{8+δ}`` → ``8+δ``
_LATEX_BRACE = re.compile(r"[_^]\{([^}]*)\}")
# Plain LaTeX numeric subscripts: ``Li_2`` → ``Li2``
_LATEX_NUM_SUBSCRIPT = re.compile(r"[_^]([0-9.]+)")
# Variable oxygen-stoichiometry suffixes: `+δ`, `-δ`, `+x`, `-y`,
# `+delta`, `±z` … Collapsed to "" so BSCCO `O_8+δ`, `O_8-x`,
# `O_8+delta` all normalize to `o8` (same parent compound, different
# doping levels). Numeric doping (e.g. `O_6.63`) is preserved.
_VAR_STOICH_SUFFIX = re.compile(
    r"[+\-±](?:delta|d|x|y|z)\b", re.IGNORECASE,
)
# Crystallographic polytype prefix: ``2H-``, ``3R-``, ``4H-``, ``1T-`` …
# (digit + single letter + hyphen at the start). These mark the
# stacking sequence of layered compounds; papers that specify it are
# still talking about the same compound family.  We keep Greek phase
# letters (κ-, λ-, α-, β-) intact because those denote genuinely
# distinct polymorphs of organic SCs.
_POLYTYPE_PREFIX = re.compile(r"^[0-9][a-z]-", re.IGNORECASE)

# Acronym / shorthand → canonical normalized formula. Papers casually
# write "YBCO" or "BSCCO" while others carry the explicit Bi₂Sr₂…
# formula; without this map they land in separate materials rows
# (audit showed YBCO split ~386 papers across two rows, BSCCO ~377
# across three). Keep the list short and scientifically unambiguous —
# every entry here should be an equivalence that any condensed-matter
# physicist would accept. Generic family names ("cuprates", "iron
# pnictides") are deliberately NOT aliased; they refer to classes,
# not compounds.
#
# Map is applied AFTER the other normalization steps, so keys are
# already lowercased and stripped. Values are existing normalized
# forms that the aggregator uses elsewhere.
_FORMULA_ALIASES: dict[str, str] = {
    # Cuprates
    "ybco":    "yba2cu3o7",
    "y-123":   "yba2cu3o7",
    "y123":    "yba2cu3o7",
    "y-124":   "yba2cu4o8",
    "y124":    "yba2cu4o8",
    "bscco":   "bi2sr2cacu2o8",   # canonical Bi-2212 stoichiometry
    "bi2212":  "bi2sr2cacu2o8",
    "bi-2212": "bi2sr2cacu2o8",
    "bi2201":  "bi2sr2cuo6",
    "bi-2201": "bi2sr2cuo6",
    "bi2223":  "bi2sr2ca2cu3o10",
    "bi-2223": "bi2sr2ca2cu3o10",
    "lsco":    "la2-xsrxcuo4",
    "lbco":    "la2-xbaxcuo4",
    "ncco":    "nd2-xcexcuo4",
    "pccco":   "pr2-xcexcuo4",
    "lco":     "la2cuo4",
    "hg-1201": "hgba2cuo4",
    "hg1201":  "hgba2cuo4",
    "hg-1212": "hgba2cacu2o6",
    "hg1212":  "hgba2cacu2o6",
    "hg-1223": "hgba2ca2cu3o8",
    "hg1223":  "hgba2ca2cu3o8",
    "tl-2201": "tl2ba2cuo6",
    "tl2201":  "tl2ba2cuo6",
    "tl-2212": "tl2ba2cacu2o8",
    "tl2212":  "tl2ba2cacu2o8",
    "tl-2223": "tl2ba2ca2cu3o10",
    "tl2223":  "tl2ba2ca2cu3o10",
}


def normalize_formula(raw: str) -> str:
    """Canonicalize a chemical formula to a grouping key.

    Rules (applied in order):

      1. ``_{xyz}`` → ``xyz``                     (LaTeX subscript strip)
      2. ``_1.23`` or ``^2`` → ``1.23`` / ``2``  (plain LaTeX sub/sup)
      3. ``{`` ``}`` ``_`` → stripped
      4. ``δ Δ``  → ``d``                         (Greek → ASCII)
      5. ``±`` ``×`` → stripped                   (symbol noise)
      6. Whitespace  → stripped
      7. ``+δ / -δ / +x / -y / +delta`` → stripped
         (variable oxygen-stoichiometry suffixes collapse into the
         parent compound)
      8. Lowercase

    This is the *grouping key*, not a display form — callers keep the
    original raw string in the ``formula`` column for UI use.

    Examples::

        Bi_2Sr_2CaCu_2O_{8+δ}    → bi2sr2cacu2o8
        Bi2Sr2CaCu2O8+delta      → bi2sr2cacu2o8
        Bi_2Sr_2Ca Cu_2 O_8-δ    → bi2sr2cacu2o8
        YBa_2Cu_3O_7-δ           → yba2cu3o7
        MgB_2                    → mgb2
        κ-(BEDT-TTF)_2Cu(NCS)_2  → κ-(bedt-ttf)2cu(ncs)2  (phase letter kept)
    """
    s = raw.strip()
    # 1. LaTeX brace subscripts first (they may contain δ/± we
    #    normalize next)
    s = _LATEX_BRACE.sub(r"\1", s)
    # 2. Plain LaTeX numeric subscripts
    s = _LATEX_NUM_SUBSCRIPT.sub(r"\1", s)
    # 3. Strip any remaining LaTeX syntax noise
    s = s.replace("_", "").replace("{", "").replace("}", "")
    # 4. Greek → ASCII for the doping marker specifically. Keep other
    #    Greeks (λ, κ, α, β prefixes) because they denote distinct
    #    polymorphs of organic superconductors.
    s = s.replace("δ", "d").replace("Δ", "d")
    # 5. Noisy symbols
    s = s.replace("±", "").replace("×", "x")
    # 6. Whitespace gone
    s = _WS.sub("", s)
    # 7. Variable stoichiometry suffixes. Runs AFTER whitespace /
    #    Greek normalization so "O_8 + delta" hits the same pattern.
    s = _VAR_STOICH_SUFFIX.sub("", s)
    # 8. Lowercase — the ONLY semantic fold we do besides the above.
    s = s.lower()
    # 9. Strip crystallographic polytype prefix ``2h-`` / ``3r-`` /
    #    ``4h-`` etc. so `2h-nbse2` collapses onto `nbse2`. The digit
    #    is preserved via the lookup below for polytypes that *are*
    #    a distinct material (none today, but room to grow).
    s = _POLYTYPE_PREFIX.sub("", s)
    # 10. Acronym alias lookup. Papers interchangeably say "YBCO" and
    #    "YBa_2Cu_3O_7-δ"; this map folds the former onto the latter
    #    so they end up in the same row.
    return _FORMULA_ALIASES.get(s, s)


# ---------------------------------------------------------------------------
# Family classification
# ---------------------------------------------------------------------------

def classify_family(formula: str) -> str | None:
    """Best-effort family bucket for the frontend family picker.

    Order matters — checks go from most-specific to most-general.
    Returns ``None`` for anything we don't recognise, which the UI
    renders as "Other".
    """
    f = formula.strip()
    fl = f.lower()

    # MgB2 is its own thing
    if re.fullmatch(r"mgb2", fl):
        return "mgb2"

    # Hydrides under pressure: H3S, LaH10, YH9, CaH6, etc.
    #
    # We tokenise the *original-case* formula into element symbols
    # ([A-Z][a-z]?) instead of substring-matching on the lowercased
    # form. The old approach matched the alternation `s|se` against
    # a lowercase string, so the `s` in `H3S` counted as a metal hit
    # for itself, and "Se" in selenides was double-counted because
    # `s` matched first. Element tokenisation eliminates both bugs.
    elements = re.findall(r"[A-Z][a-z]?", f)
    high_h = bool(re.search(r"H(?:[2-9]|1[0-9])\b", f))
    if high_h and "O" not in elements and "C" not in elements:
        partners = {"S", "Se", "La", "Y", "Ca", "Mg", "Sr", "Ba",
                    "Th", "Sc", "Yb", "Ce", "Pr", "Nd"}
        if any(e in partners for e in elements):
            return "hydride"

    # Fullerides: superconducting alkali-doped fullerenes. The
    # industry-standard family label is "fulleride" — coined after
    # Rosseinsky et al. (K₃C₆₀ Tc=19 K, 1991) and consistently used
    # in condensed-matter reviews (Gunnarsson 1997, Capone 2009,
    # Ganin et al. 2008 for Cs₃C₆₀ at Tc≈38 K under pressure).
    #
    # Detection: tokenise to element symbols on the original-case
    # formula and look for any carbon atom with stoichiometry 60,
    # 70, 76, or 84 (the common closed-cage fullerene sizes). This
    # catches ``C_60``, ``K_3C_60``, ``Rb_3C_60``, ``Cs_3C_60``,
    # ``NaRb_2C_60``, solvent intercalates ``C_60/C_12H_26`` etc.,
    # while safely rejecting false positives like ``Sc60Ti40``
    # where ``60`` is a scandium stoichiometry, not a cage size.
    for el, cnt in re.findall(r"([A-Z][a-z]?)[_\s]*(\d+)?", f):
        if el == "C" and cnt in ("60", "70", "76", "84"):
            return "fulleride"

    # Iron-based: Fe with As, Se, Te, P, or a "11"/"122"/"1111" motif
    if "fe" in fl and re.search(r"(as|se|te|p)", fl):
        return "iron_based"

    # Cuprate phase-label shorthand — papers often write "BSCCO",
    # "YBCO", "Bi-2212", "Bi(Pb)-2212", "Hg-1223", "Pb-Bi2212" etc.
    # instead of the full stoichiometry. The cu+o test below misses
    # these because the shorthand has no 'o', and the conventional
    # "pb"/"hg" check further down would grab the Pb-doped ones.
    # Catching them up front fixes both.
    if re.search(r"bscco|ybco|lsco|tbcco", fl):
        return "cuprate"
    if re.search(r"\b(pb|bi|tl|hg)[\s\-()a-z]*[12][12][0-9]{2}\b", fl):
        return "cuprate"
    if re.search(r"\by[\s\-]*12[3-8]\b", fl):
        return "cuprate"  # YBCO n-layer shorthand: Y-123, Y-124, Y-125

    # Nickelates (Ni + O oxides, no Cu or Fe partner). Covers the
    # infinite-layer family (Nd₀·₈Sr₀·₂NiO₂ on SrTiO₃, Li et al. 2019,
    # Tc≈15 K), bulk Ruddlesden-Popper stacks (La₃Ni₂O₇, Sun et al.
    # 2023, Tc≈80 K at 14 GPa), and the growing 2024+ cohort. We
    # check the tokenized element list (``elements`` from the hydride
    # branch above) instead of a lowercase substring so "in" / other
    # elements containing 'n' or 'i' don't false-positive.
    if (
        "Ni" in elements
        and "O" in elements
        and "Cu" not in elements
        and "Fe" not in elements
    ):
        return "nickelate"

    # Cuprates: must contain both Cu and O, plus a rare-earth / alkaline
    # earth cation typical of high-Tc cuprates
    if "cu" in fl and "o" in fl and re.search(r"(la|y|ba|sr|ca|bi|hg|tl|nd|sm|gd)", fl):
        return "cuprate"

    # Heavy-fermion: actinides / lanthanides we care about
    if re.search(r"(ube|cein|ceco|cecu|ypb|yrh|uru)", fl):
        return "heavy_fermion"

    # Conventional low-Tc: Nb3Sn, Nb3Ge, V3Si, NbTi, Pb, Hg, Sn, In, MgB2...
    if re.search(r"(nb3sn|nb3ge|v3si|nbti|pb\b|hg\b|\bsn\b)", fl):
        return "conventional"

    return None


# ---------------------------------------------------------------------------
# Row → aggregated material
# ---------------------------------------------------------------------------

@dataclass
class _Aggregate:
    formula: str
    formula_normalized: str
    family: str | None = None
    tc_max: float | None = None
    tc_max_conditions: str | None = None
    tc_ambient: float | None = None  # best Tc at pressure == 0
    discovery_year: int | None = None  # NIMS doesn't ship this — left None
    records: list[dict[str, Any]] = field(default_factory=list)

    def ingest(self, row: dict[str, Any]) -> None:
        self.records.append(row)
        tc = row.get("tc")
        if tc is None:
            return
        if self.tc_max is None or tc > self.tc_max:
            self.tc_max = tc
            conds: list[str] = []
            if row.get("pressure"):
                conds.append(f"P={row['pressure']} GPa")
            if row.get("doping"):
                conds.append(f"x={row['doping']}")
            if row.get("structure"):
                conds.append(str(row["structure"]))
            self.tc_max_conditions = ", ".join(conds) or None
        # Ambient bucket — records with no pressure column or pressure == 0
        # are treated as ambient. NIMS rows without a pressure field are
        # overwhelmingly ambient-pressure measurements.
        pressure = row.get("pressure")
        if pressure is None or pressure == 0:
            if self.tc_ambient is None or tc > self.tc_ambient:
                self.tc_ambient = tc

    def derive_v2(self) -> dict[str, Any]:
        """Compute the v2 summary columns the CSV can plausibly support.

        Fields we *can't* fill from NIMS (pairing_symmetry, hc2_tesla,
        lambda_eph, competing orders) are left None — the arXiv NER path
        populates those via the aggregator.
        """
        # Most common non-null structure string across records.
        struct_counter: Counter[str] = Counter()
        for r in self.records:
            s = r.get("structure")
            if isinstance(s, str) and s.strip():
                struct_counter[s.strip()] += 1
        crystal_structure = (
            struct_counter.most_common(1)[0][0] if struct_counter else None
        )

        # Pressure type: if any record has positive pressure, flag the
        # material as studied under hydrostatic pressure.
        has_pressure = any(
            isinstance(r.get("pressure"), (int, float)) and r["pressure"] > 0
            for r in self.records
        )
        pressure_type = "hydrostatic" if has_pressure else None

        # Distinct references → a rough "how many sources cite this"
        # number. NIMS bundles one row per measurement so this is an
        # overestimate of independent papers, but still better than 0.
        refs = {
            r.get("reference") for r in self.records
            if isinstance(r.get("reference"), str) and r["reference"].strip()
        }
        total_papers = len(refs)

        ambient_sc: bool | None = None
        if self.tc_ambient is not None:
            ambient_sc = True
        elif any(r.get("tc") is not None for r in self.records):
            # We have Tc data but none of it is ambient — mark False.
            ambient_sc = False

        return {
            "crystal_structure": (crystal_structure or None),
            "tc_ambient": self.tc_ambient,
            "ambient_sc": ambient_sc,
            "pressure_type": pressure_type,
            "total_papers": total_papers,
        }


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    s = value.strip()
    if not s or s in {"-", "n/a", "na", "nan"}:
        return None
    try:
        return float(s)
    except ValueError:
        # NIMS sometimes uses "90-95" ranges — take the midpoint
        m = re.match(r"^([0-9.]+)\s*-\s*([0-9.]+)$", s)
        if m:
            return (float(m.group(1)) + float(m.group(2))) / 2
        return None


def _material_id(normalized: str) -> str:
    """Deterministic 100-char primary key. Truncates long formulas and
    appends a short hash so collisions are astronomically unlikely."""
    import hashlib

    if len(normalized) <= 90:
        return f"nims:{normalized}"
    h = hashlib.sha1(normalized.encode()).hexdigest()[:8]
    return f"nims:{normalized[:80]}:{h}"


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

async def load_csv(csv_path: Path, limit: int | None, dry_run: bool) -> int:
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        log.info("CSV headers: %s", headers)

        col_formula = _find_col(headers, "formula")
        col_tc = _find_col(headers, "tc")
        col_structure = _find_col(headers, "structure")
        col_pressure = _find_col(headers, "pressure")
        col_doping = _find_col(headers, "doping")
        col_reference = _find_col(headers, "reference")

        if not col_formula or not col_tc:
            log.error(
                "Could not locate formula/tc columns. "
                "Headers=%s; aliases=%s",
                headers,
                {k: v for k, v in COLUMN_ALIASES.items() if k in ("formula", "tc")},
            )
            return 1

        log.info(
            "Columns: formula=%r tc=%r structure=%r pressure=%r doping=%r ref=%r",
            col_formula, col_tc, col_structure, col_pressure, col_doping, col_reference,
        )

        aggregates: dict[str, _Aggregate] = {}
        skipped = 0
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            raw_formula = (row.get(col_formula) or "").strip()
            if not raw_formula:
                skipped += 1
                continue
            normalized = normalize_formula(raw_formula)
            agg = aggregates.get(normalized)
            if agg is None:
                agg = _Aggregate(
                    formula=raw_formula,
                    formula_normalized=normalized,
                    family=classify_family(normalized),
                )
                aggregates[normalized] = agg
            record = {
                "tc": _parse_float(row.get(col_tc)),
                "structure": (row.get(col_structure) or None) if col_structure else None,
                "pressure": _parse_float(row.get(col_pressure)) if col_pressure else None,
                "doping": (row.get(col_doping) or None) if col_doping else None,
                "reference": (row.get(col_reference) or None) if col_reference else None,
            }
            # drop None keys so the JSONB stays tidy
            record = {k: v for k, v in record.items() if v is not None}
            agg.ingest(record)

        log.info(
            "Parsed %d unique formulas from %d rows (skipped %d blanks)",
            len(aggregates),
            i + 1 if aggregates else 0,
            skipped,
        )

    if dry_run:
        preview = list(aggregates.values())[:5]
        for agg in preview:
            log.info(
                "DRY %s | family=%s tc_max=%s records=%d",
                agg.formula, agg.family, agg.tc_max, len(agg.records),
            )
        return 0

    Session = _session_factory()
    async with Session() as db:
        inserted = 0
        for agg in aggregates.values():
            v2 = agg.derive_v2()
            values = dict(
                id=_material_id(agg.formula_normalized),
                formula=agg.formula[:200],
                formula_normalized=agg.formula_normalized[:200],
                family=agg.family,
                tc_max=agg.tc_max,
                tc_max_conditions=(agg.tc_max_conditions or None),
                discovery_year=agg.discovery_year,
                status="active_research",
                records=agg.records,
                **v2,
            )
            stmt = (
                pg_insert(materials_table)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[materials_table.c.id],
                    set_={
                        "formula": agg.formula[:200],
                        "family": agg.family,
                        "tc_max": agg.tc_max,
                        "tc_max_conditions": agg.tc_max_conditions,
                        "records": agg.records,
                        **v2,
                    },
                )
            )
            await db.execute(stmt)
            inserted += 1
            if inserted % 500 == 0:
                await db.commit()
                log.info("  upserted %d/%d ...", inserted, len(aggregates))
        await db.commit()
        log.info("NIMS import complete: %d materials upserted", inserted)

    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Import NIMS SuperCon CSV into materials table")
    parser.add_argument("--csv", required=True, type=Path, help="Path to NIMS SuperCon CSV")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N rows (debug)")
    parser.add_argument("--dry-run", action="store_true", help="Parse + classify only, no DB writes")
    args = parser.parse_args()

    if not args.csv.is_file():
        log.error("CSV not found: %s", args.csv)
        return 1

    return asyncio.run(load_csv(args.csv, args.limit, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
