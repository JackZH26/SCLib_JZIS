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
    # 3. Strip any remaining LaTeX syntax noise.
    #    "$" is the math-mode delimiter — papers write H$_{3}$S, and
    #    without dropping the dollars we got TWO grouping keys
    #    ("h$3$s" vs "h3s") for the same compound. The pre-fix corpus
    #    has ~680 such duplicated rows; alembic 0013 dedupes them.
    s = (s.replace("_", "")
           .replace("{", "")
           .replace("}", "")
           .replace("$", ""))
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

    Families (2026-05 revision):
      mgb2, hydride, fulleride, iron_based, cuprate, nickelate,
      heavy_fermion, kagome, organic, bismuthate, borocarbide,
      ruthenate, chalcogenide, elemental, conventional
    """
    f = formula.strip()
    fl = f.lower()

    # Element tokenisation — used by many branches below
    elements = re.findall(r"[A-Z][a-z]?", f)
    el_set = set(elements)

    # ── MgB2 ──
    if re.fullmatch(r"mg[\d.\-]*(?:al[\d.]*)?b2", fl):
        return "mgb2"  # Also catches Mg1-xAlxB2

    # ── Hydrides under pressure ──
    # H3S, LaH10, YH9, CaH6, ScLuH12, etc.
    high_h = bool(re.search(r"H(?:[2-9]|1[0-9])(?![0-9])", f))
    if high_h and "O" not in el_set and "C" not in el_set:
        partners = {"S", "Se", "La", "Y", "Ca", "Mg", "Sr", "Ba",
                    "Th", "Sc", "Yb", "Ce", "Pr", "Nd", "Lu", "Ac",
                    "Be", "Hf", "Na", "Li", "K", "Zr"}
        if any(e in partners for e in el_set):
            return "hydride"

    # ── Fullerides ──
    for el, cnt in re.findall(r"([A-Z][a-z]?)[_\s]*(\d+)?", f):
        if el == "C" and cnt in ("60", "70", "76", "84"):
            return "fulleride"

    # ── Kagome vanadium antimonides ──
    # CsV3Sb5, KV3Sb5, RbV3Sb5 — the AV3Sb5 family
    if "V" in el_set and "Sb" in el_set:
        if re.search(r"v3sb5", fl):
            return "kagome"

    # ── Iron-based ──
    # Fe with pnictide/chalcogenide partner: FeAs, FeSe, FeTe, FeP, FeS
    if "Fe" in el_set:
        if {"As"} & el_set or {"Te"} & el_set or {"P"} & el_set:
            return "iron_based"
        # FeSe / FeS — important iron-chalcogenide SCs
        if {"Se"} & el_set or ({"S"} & el_set and "Cu" not in el_set):
            return "iron_based"
        # Iron-based shorthands: "122", "1111", "11" structure motifs
        if re.search(r"bafe2as2|bafe2|lafeaso|lifeas|nafeas", fl):
            return "iron_based"

    # ── Cuprate phase-label shorthand ──
    if re.search(r"bscco|ybco|lsco|tbcco|ncco|pccco", fl):
        return "cuprate"
    if re.search(r"(pb|bi|tl|hg)[\s\-()a-z]*[12][12][0-9]{2}", fl):
        return "cuprate"
    if re.search(r"y[\s\-]*12[3-8]", fl):
        return "cuprate"

    # ── Nickelates ──
    if (
        "Ni" in el_set
        and "O" in el_set
        and "Cu" not in el_set
        and "Fe" not in el_set
        and "B" not in el_set  # exclude borocarbides like YNi2B2C
    ):
        return "nickelate"

    # ── Cuprates (full stoichiometry) ──
    if "Cu" in el_set and "O" in el_set:
        re_cation = r"(la|y|ba|sr|ca|bi|hg|tl|nd|sm|gd|pr|eu|tb|dy|ho|er|tm)"
        if re.search(re_cation, fl):
            return "cuprate"

    # ── Organic superconductors ──
    # BEDT-TTF (ET), TMTSF (Bechgaard salts), BETS, TTF-TCNQ, picene, etc.
    organic_patterns = (
        r"bedt[\s\-]?ttf|κ-\(et\)|κ-\(bedt|tmtsf|bets|"
        r"dmit|tcnq|picene|phenanthrene|coronene|chrysene"
    )
    if re.search(organic_patterns, fl):
        return "organic"

    # ── Bismuthates ──
    # BaPb1-xBixO3, Ba1-xKxBiO3 — the oxide family with Bi + O
    if "Bi" in el_set and "O" in el_set and "Cu" not in el_set:
        if "Ba" in el_set or "Sr" in el_set:
            if "Se" not in el_set and "Te" not in el_set:
                return "bismuthate"
    # BiS2-based layered SCs: LaO0.5F0.5BiS2, NdOBiS2
    if re.search(r"bis2", fl):
        return "bismuthate"

    # ── Heavy-fermion ──
    # Uranium compounds: UTe2, UPt3, URhGe, UCoGe, UPd2Al3, UGe2, etc.
    if "U" in el_set and len(el_set) >= 2:
        hf_partners = {"Te", "Pt", "Rh", "Co", "Pd", "Ge", "Be", "Ru", "Si", "Ir", "Ni"}
        if el_set & hf_partners:
            return "heavy_fermion"
    # Cerium compounds: CeIn3, CeCoIn5, CeCu2Si2, CePt3Si, CeRhIn5, CeRh2As2
    if "Ce" in el_set and len(el_set) >= 2:
        return "heavy_fermion"
    # PrOs4Sb12 (skutterudite heavy-fermion)
    if re.search(r"pros4sb12|pros4|prpt4ge12", fl):
        return "heavy_fermion"
    # YbRh2Si2, YbAlB4
    if "Yb" in el_set and el_set & {"Rh", "Al", "Pd", "Ni"}:
        return "heavy_fermion"
    # Legacy patterns for partial matches
    if re.search(r"ube13|cecu2si2|upd2al3|uru2si2|cecoin5", fl):
        return "heavy_fermion"

    # ── Borocarbides ──
    # RNi2B2C: YNi2B2C, LuNi2B2C, ErNi2B2C, HoNi2B2C, etc.
    if "Ni" in el_set and "B" in el_set and "C" in el_set:
        if re.search(r"ni2b2c", fl):
            return "borocarbide"

    # ── Ruthenates ──
    # Sr2RuO4 — the canonical spin-triplet candidate
    if "Ru" in el_set and "O" in el_set:
        if "Sr" in el_set or "Ca" in el_set:
            return "ruthenate"

    # ── Chalcogenides (transition-metal dichalcogenides + misc) ──
    # NbSe2, TaS2, MoS2, MoTe2, PdTe2, PbTaSe2, CuxBi2Se3, 4Hb-TaS2, etc.
    chalc = {"Se", "Te", "S"}
    tm_chalc = {"Nb", "Ta", "Mo", "W", "Ti", "Zr", "Hf", "Pd", "Pt", "Ir", "Re"}
    if el_set & chalc and el_set & tm_chalc:
        # Exclude iron-based (already caught) and bismuthates
        if "Fe" not in el_set:
            return "chalcogenide"
    # Bi2Se3/Bi2Te3 topological SCs (Cu/Sr-doped)
    if "Bi" in el_set and el_set & {"Se", "Te"} and "O" not in el_set:
        return "chalcogenide"

    # ── Graphite intercalation compounds (GIC) ──
    # CaC6, YbC6, KC8 — superconducting graphite intercalants
    if re.search(r"^[a-z]{1,2}c[68]\b", fl):
        return "conventional"

    # ── Elemental superconductors ──
    # Single elements known to superconduct: Nb, Al, Pb, Sn, In, V, Ta, etc.
    _SC_ELEMENTS = {
        "Nb", "Al", "Pb", "Sn", "In", "V", "Ta", "Re", "Ti", "Zr",
        "Hf", "Mo", "W", "Ru", "Os", "Ir", "Rh", "Zn", "Ga", "La",
        "Tl", "Bi", "Cd", "Th", "Pa", "Be", "Am",
    }
    if len(elements) == 1 and elements[0] in _SC_ELEMENTS:
        return "elemental"
    # Hg / Sn / Pb / In as standalone or with simple numerals
    if re.fullmatch(r"(nb|al|pb|sn|in|v|ta|re|ti|la|bi|hg)\d*", fl):
        return "elemental"

    # ── Conventional (A15 compounds, nitrides, borides, alloys) ──
    # A15: Nb3Sn, Nb3Ge, Nb3Al, V3Si, V3Ga, Cr3Ir
    if re.search(r"nb3(?:sn|ge|al|ga|si)|v3(?:si|ga)|cr3ir", fl):
        return "conventional"
    # Nitrides: NbN, TiN, NbTiN, MoN, VN, ZrN
    if re.search(r"^(?:nb|ti|mo|v|zr|hf|ta)[\d.]*n[\d.]*$", fl):
        return "conventional"
    # Binary alloys: NbTi, MoRe, MoGe, NbZr, etc.
    if re.search(r"nbti|more|moge|nbzr|inox|srpt3p", fl):
        return "conventional"
    # Borides (non-MgB2): ZrB12, YB6, TaB2
    if re.search(r"^(?:zr|y|ta|lu|nb|la|sc)b\d+", fl):
        return "conventional"
    # Chevrel phases: PbMo6S8, SnMo6S8, etc.
    if re.search(r"mo6s8|mo6se8", fl):
        return "conventional"
    # Spinel: LiTi2O4
    if re.search(r"liti2o4", fl):
        return "conventional"
    # Pyrochlore osmates/rhenates: Cd2Re2O7, KOs2O6, RbOs2O6
    if re.search(r"cd2re2o7|os2o6", fl):
        return "conventional"
    # MgCNi3 — perovskite conventional
    if re.search(r"mgcni3", fl):
        return "conventional"
    # Quasi-1D: K2Cr3As3, Rb2Cr3As3
    if re.search(r"cr3as3", fl):
        return "conventional"

    # Legacy catch-all
    if re.search(r"nb3sn|nb3ge|v3si|nbti", fl):
        return "conventional"

    return None


# ---------------------------------------------------------------------------
# is_unconventional inference from family
# ---------------------------------------------------------------------------

# Definitive mapping from family to is_unconventional. These are
# consensus assignments any condensed-matter physicist would agree with.
# Families not in either set are left NULL (no inference).
_UNCONVENTIONAL_FAMILIES = frozenset({
    "cuprate",        # d-wave, beyond BCS
    "iron_based",     # s±-wave, magnetic fluctuation mediated
    "nickelate",      # d-wave / s±, strong correlations
    "heavy_fermion",  # multiple exotic pairing channels
    "organic",        # proximity to Mott insulator, spin fluctuations
    "ruthenate",      # candidate spin-triplet (debated but consensus: unconventional)
    "kagome",         # unconventional due to competing orders / topology
})
_CONVENTIONAL_FAMILIES = frozenset({
    "conventional",   # BCS / electron-phonon
    "mgb2",           # phonon-mediated (two-gap but still conventional)
    "elemental",      # BCS
    "borocarbide",    # phonon-mediated
})
# Deliberately omitted (cannot assign without per-material info):
# hydride — mostly phonon-mediated but some have unconventional claims
# fulleride — debated (some claim Jahn-Teller / electronic mechanism)
# bismuthate — debated (CDW proximity)
# chalcogenide — varies (NbSe2 conventional, CuxBi2Se3 topological)


def infer_unconventional(family: str | None) -> bool | None:
    """Infer is_unconventional from family classification.

    Returns True/False for families with clear consensus, None for
    ambiguous or unknown families.
    """
    if family in _UNCONVENTIONAL_FAMILIES:
        return True
    if family in _CONVENTIONAL_FAMILIES:
        return False
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
                # classify_family expects the ORIGINAL-case formula so
                # the element-tokenising rules (hydride / fulleride /
                # nickelate — which all rely on re.findall(r"[A-Z][a-z]?",
                # f)) can actually fire. Passing the lowercased
                # ``normalized`` here was a silent bug that left every
                # NIMS row ineligible for those three families and, worse,
                # let a pre-2026-04 version of the hydride rule match the
                # lowercase "rh" substring of rhodium compounds. See
                # alembic 0011 for the one-shot backfill.
                agg = _Aggregate(
                    formula=raw_formula,
                    formula_normalized=normalized,
                    family=classify_family(raw_formula),
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
