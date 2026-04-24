"""Material NER v2 via Gemini 2.5 Flash.

Returns a list of superconductor records extracted from the full text
of a paper. The v2 schema (see docs/SCLib_Materials_Schema_v2.md)
extracts ~20 fields per material so downstream aggregation can fill in
structure, SC parameters, competing orders, sample/pressure conditions,
and a handful of flags.

Design:
  1. Classify the paper (computational / experimental / theoretical)
     from title + abstract keyword signals. Different paper types yield
     different fields reliably — lambda_eph / omega_log_k only come
     from DFT / Eliashberg papers — so we pick a prompt specialised for
     that bucket.
  2. Call Gemini with the v2 prompt, temperature 0, JSON-only response.
  3. Defensively parse + coerce numeric fields (strings like "150 T"
     become 150.0, ranges like "80-95 K" become the midpoint).
  4. Fallback: apply STRUCTURE_PHASE_PATTERNS regex to the raw text so
     RP / cuprate family tags (1212, 2222, infinite_layer, YBCO…) get
     filled in even when the LLM misses them.

The module calls google-genai synchronously; the pipeline wraps calls
in ``asyncio.to_thread`` to keep the orchestration loop non-blocking.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Literal

from google import genai
from google.genai import types as genai_types

from ingestion.config import get_settings
from ingestion.models import ParsedPaper

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper-type classifier
# ---------------------------------------------------------------------------

PaperType = Literal["computational", "experimental", "theoretical"]

_CALC_KEYWORDS = [
    "first-principles", "first principles", "dft", "density functional",
    "eliashberg", "allen-dynes", "allen dynes", "electron-phonon",
    "electron phonon", "mcmillan", "phonon calculation", "ab initio",
    "ab-initio", "wannier", "epw",
]
_EXP_KEYWORDS = [
    "single crystal", "thin film", "polycrystal", "polycrystalline",
    "resistivity measurement", "susceptibility", "specific heat",
    "musr", "μsr", "arpes", "stm", "scanning tunneling",
    "neutron scattering", "sample preparation", "synthesis",
    "x-ray diffraction", "xrd",
]


def classify_paper_type(title: str, abstract: str) -> PaperType:
    """Pick the extraction bucket for a paper from title + abstract signals.

    Two buckets dominate the SC literature: DFT / Eliashberg theory
    papers that report lambda_eph / omega_log_k, and experimental
    papers that report Tc / Hc2 / transport. A handful are pure
    phenomenology ("theoretical") and yield neither reliably.
    """
    text = (title + " " + abstract).lower()
    calc_score = sum(1 for k in _CALC_KEYWORDS if k in text)
    exp_score = sum(1 for k in _EXP_KEYWORDS if k in text)
    if calc_score >= 2 and calc_score >= exp_score:
        return "computational"
    if exp_score >= 2:
        return "experimental"
    return "theoretical"


# ---------------------------------------------------------------------------
# Structure-phase regex fallback
# ---------------------------------------------------------------------------

# Patterns go from most-specific (RP numeric labels) to family aliases.
# We match case-insensitively against the full body text.
STRUCTURE_PHASE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b1212\b"),                              "1212"),
    (re.compile(r"\b2222\b"),                              "2222"),
    (re.compile(r"\b1313\b"),                              "1313"),
    (re.compile(r"infinite[- ]?layer"),                    "infinite_layer"),
    (re.compile(r"\bRuddlesden[- ]Popper\s*n\s*=\s*1\b"),  "RP_n1"),
    (re.compile(r"\bRuddlesden[- ]Popper\s*n\s*=\s*2\b"),  "RP_n2"),
    (re.compile(r"\bRuddlesden[- ]Popper\s*n\s*=\s*3\b"),  "RP_n3"),
    (re.compile(r"\b(?:La214|LSCO|La2CuO4)\b",  re.I),     "cuprate_214"),
    (re.compile(r"\b(?:YBCO|Y[- ]?123|YBa2Cu3O)\b", re.I), "cuprate_123"),
    (re.compile(r"\bBi[- ]?2212\b", re.I),                 "cuprate_2212"),
    (re.compile(r"\bBi[- ]?2223\b", re.I),                 "cuprate_2223"),
    (re.compile(r"\bHg12(?:01|12|23)\b", re.I),            "cuprate_Hg"),
    (re.compile(r"\bTl[- ]?2212\b|\bTl[- ]?2223\b", re.I), "cuprate_Tl"),
]


def extract_structure_phase(text: str) -> str | None:
    """Return the first matching RP / cuprate family tag, else None."""
    for pat, phase in STRUCTURE_PHASE_PATTERNS:
        if pat.search(text):
            return phase
    return None


# ---------------------------------------------------------------------------
# Gemini prompts
# ---------------------------------------------------------------------------

# NOTE: interpolate with str.replace("{{BODY}}", ...) not str.format —
# the prompt contains literal JSON-schema hints that format would
# misread as field references.

_V2_PROMPT_CORE = """\
Extract superconducting material data from the text below. Return a
JSON array only. One object per (material, measurement) pair. If no
superconducting material is measured, return [].

REQUIRED per record:
- formula: chemical formula as written in the text (e.g. "La3Ni2O7")
- tc_kelvin: critical temperature in Kelvin, null if not stated
- tc_type: "onset" | "zero_resistance" | "midpoint" | "unknown"
- pressure_gpa: MUST be null unless the paper explicitly states a
                pressure for THIS measurement. Use 0.0 ONLY when the
                text literally says "ambient pressure", "atmospheric
                pressure", "P = 0", or "zero pressure". If the paper
                doesn't mention pressure, emit null — do NOT default
                to 0.0. Emit the numeric value in GPa when stated.
- measurement: "resistivity" | "susceptibility" | "specific_heat" |
               "muSR" | "ARPES" | "STM" | "neutron" | "unknown"
- confidence: 0.0-1.0 — your confidence the text actually reports this
- evidence_type: "primary" | "cited". Use "primary" ONLY when the
                 paper ITSELF measures, computes, synthesizes, or
                 characterizes this material's Tc. Use "cited" for
                 numbers taken from the literature — introduction
                 surveys, comparison tables, "previously reported"
                 mentions, reference to prior work by other groups
                 (e.g. "LaH10 has Tc≈260 K [Drozdov 2019]" in the
                 intro). When in doubt, default to "cited". A formula
                 whose Tc comes right before/after a bracketed citation
                 "[12]" or a phrase like "reported by X et al" is
                 ALWAYS "cited".

EXTRACT IF PRESENT (omit or set null otherwise):
- pairing_symmetry: "d-wave" | "s-wave" | "s_pm" | "p-wave" | "unknown"
- gap_structure: "full_gap" | "nodal" | "multi_gap" | "unknown"
- crystal_structure: space group or structure type (e.g. "I4/mmm")
- space_group: space group symbol or number (e.g. "I4/mmm (#139)")
- structure_phase: RP or cuprate phase label ("1212", "2222", "1313",
                   "infinite_layer", "cuprate_214", "cuprate_123", ...)
- lattice_a, lattice_c: lattice parameters in angstrom (numbers)
- t_cdw_k, t_sdw_k, t_afm_k: competing-order transition temps in K
- rho_exponent: normal-state resistivity exponent n (rho ~ T^n)
- competing_order: "CDW" | "AFM" | "SDW" | "Mott_insulator" | "PDW"
- hc2_tesla: upper critical field in Tesla
- hc2_conditions: conditions string for Hc2 (e.g. "0 K, H parallel c")
- lambda_eph: electron-phonon coupling constant lambda
- omega_log_k: logarithmic average phonon frequency in Kelvin
- rho_s_mev: superfluid stiffness rho_s in meV
- ambient_sc: true iff superconducting at 0 GPa
- sample_form: "single_crystal" | "polycrystal" | "thin_film" |
               "powder" | "wire"
- substrate: substrate material for thin films
- pressure_type: "hydrostatic" | "uniaxial" | "chemical" | "none"
- doping_type: "hole" | "electron" | "isovalent" | "none"
- doping_level: numeric doping x (0..1 range)
- is_topological: true iff the paper claims topological SC features
- is_unconventional: true iff explicitly described as unconventional
                     / non-BCS
- is_2d_or_interface: true iff 2D material or interface superconductor
- disputed: true iff the paper mentions contested / retracted results

RULES:
- Only extract materials explicitly measured for superconductivity.
- Do not invent data. Fields not in the text must be null / omitted.
- If Tc > 300 K or Tc < 0.01 K, set confidence <= 0.3.
- Distinguish experimental measurements from theoretical predictions.
  If the paper only predicts Tc from DFT, mark measurement="unknown"
  and confidence <= 0.5.
- evidence_type is orthogonal to confidence. A paper may cite a
  prior measurement with 100% confidence — that's still "cited",
  not "primary". primary == THIS paper IS the source. Review /
  theory-survey introductions are the most common "cited" region.
  Materials in Table 1 / benchmark columns are usually "cited"
  unless the paper explicitly frames them as newly measured here.
- For structure_phase, look for patterns like "1212 phase", "n=2 RP",
  "infinite layer", "YBCO", "La2CuO4" etc.
- For rho_exponent, look for "T-linear" (n=1.0), "T^2" (n=2.0),
  "rho proportional to T^n with n=..."
- lambda_eph / omega_log_k ONLY from DFT or Eliashberg papers.

Text:
---
{{BODY}}
---
"""

# The computational bucket adds stronger emphasis on DFT outputs, and
# tells the model it *should* see lambda_eph / omega_log_k.
_V2_PROMPT_COMPUTATIONAL_PREFIX = """\
This paper reports first-principles / DFT / Eliashberg calculations.
Pay particular attention to the computed electron-phonon coupling
constant (lambda_eph), logarithmic-average phonon frequency
(omega_log_k, in Kelvin), and any McMillan / Allen-Dynes formula
inputs. If the paper uses mu* (Coulomb pseudopotential), record the
value in the notes but do not emit a field for it.

"""


def _build_prompt(body: str, paper_type: PaperType) -> str:
    core = _V2_PROMPT_CORE.replace("{{BODY}}", body[:_MAX_CHARS])
    if paper_type == "computational":
        return _V2_PROMPT_COMPUTATIONAL_PREFIX + core
    return core


# Truncate the text we hand to Gemini so one enormous paper cannot blow
# the context window. Abstract + first ~16k chars of body is plenty for
# NER — structural fields live in the intro and the experimental section.
_MAX_CHARS = 16_000


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    settings = get_settings()
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_region,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Complete list of v2 fields we expose on each extracted record. The
# aggregator later consumes these to build the material-level summary.
_V2_FIELDS = (
    "tc_kelvin", "tc_type", "pressure_gpa", "measurement", "confidence",
    "evidence_type",
    "pairing_symmetry", "gap_structure",
    "crystal_structure", "space_group", "structure_phase",
    "lattice_a", "lattice_c",
    "t_cdw_k", "t_sdw_k", "t_afm_k", "rho_exponent", "competing_order",
    "hc2_tesla", "hc2_conditions",
    "lambda_eph", "omega_log_k", "rho_s_mev",
    "ambient_sc", "sample_form", "substrate",
    "pressure_type", "doping_type", "doping_level",
    "is_topological", "is_unconventional", "is_2d_or_interface",
    "disputed",
)

# evidence_type is a string enum with a strict value set. Anything
# outside the set is dropped so aggregator filtering stays a simple
# equality check ("cited" → skip).
_EVIDENCE_TYPES = {"primary", "cited"}

_NUMERIC_FIELDS = {
    "tc_kelvin", "pressure_gpa", "confidence",
    "lattice_a", "lattice_c",
    "t_cdw_k", "t_sdw_k", "t_afm_k", "rho_exponent",
    "hc2_tesla", "lambda_eph", "omega_log_k", "rho_s_mev",
    "doping_level",
}
_BOOL_FIELDS = {
    "ambient_sc", "is_topological", "is_unconventional",
    "is_2d_or_interface", "disputed",
}


def extract_materials(parsed: ParsedPaper) -> list[dict[str, Any]]:
    """Call Gemini and parse the JSON response. Returns [] on failure.

    Each record is a plain dict with the v2 fields. Missing fields are
    simply absent (never null) so the aggregator can tell "LLM didn't
    emit" from "LLM emitted null".
    """
    settings = get_settings()
    body = _assemble_text(parsed)
    if not body.strip():
        return []

    paper_type = classify_paper_type(parsed.meta.title, parsed.meta.abstract)
    prompt = _build_prompt(body, paper_type)

    try:
        resp = _client().models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini NER call failed for %s: %s", parsed.meta.paper_id, e)
        return []

    text = (resp.text or "").strip()
    if not text:
        return []

    records = _parse_json(text)
    if records is None:
        log.warning("Gemini NER returned non-JSON for %s: %r",
                    parsed.meta.paper_id, text[:200])
        return []

    # Fallback: if the LLM didn't tag a structure_phase anywhere,
    # try the regex pass over the full body. That's good enough to
    # catch RP / cuprate labels that the LLM sometimes hallucinates
    # its way past.
    phase_fallback = extract_structure_phase(body)

    cleaned: list[dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict) or "formula" not in r:
            continue
        record: dict[str, Any] = {
            "formula": str(r["formula"]).strip(),
            "paper_type": paper_type,
        }
        for field in _V2_FIELDS:
            if field not in r:
                continue
            value = r[field]
            if value is None or value == "":
                continue
            if field in _NUMERIC_FIELDS:
                coerced = _coerce_float(value)
                if coerced is None:
                    continue
                record[field] = coerced
            elif field in _BOOL_FIELDS:
                record[field] = _coerce_bool(value)
            else:
                record[field] = str(value).strip() or None

        # Regex fallback for structure_phase
        if "structure_phase" not in record and phase_fallback:
            record["structure_phase"] = phase_fallback

        # Normalize evidence_type to a known enum value or drop it.
        # Missing/invalid is left absent — the aggregator treats absent
        # as "primary" for backward compatibility with legacy records.
        ev = record.get("evidence_type")
        if ev is not None:
            ev_lower = str(ev).strip().lower()
            if ev_lower in _EVIDENCE_TYPES:
                record["evidence_type"] = ev_lower
            else:
                record.pop("evidence_type", None)

        # Defensive: enforce the spec's confidence-downgrade for
        # implausibly high Tc values.
        tc = record.get("tc_kelvin")
        conf = record.get("confidence") or 0.0
        if tc is not None and (tc > 300 or tc < 0.01) and conf >= 0.3:
            record["confidence"] = 0.3

        # NOTE: we used to default ambient_sc=True when pressure_gpa==0,
        # but ambient vs unknown is exactly what the new prompt asks
        # the LLM to distinguish. The historical fallback silently
        # promoted every "LLM didn't mention pressure" record into a
        # confident ambient-SC claim, which polluted the corpus (see
        # alembic 0009). We rely entirely on the LLM's ambient_sc
        # field now; if it's missing, ambient_sc stays None / unknown.

        cleaned.append(record)

    return cleaned


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assemble_text(parsed: ParsedPaper) -> str:
    parts = [f"Title: {parsed.meta.title}", f"Abstract: {parsed.meta.abstract}"]
    # Extra sections are useful for the extended field extraction — the
    # body of an experimental paper is where Hc2 / sample form / doping
    # are reported, not in the abstract. Pull the first ~8 sections.
    for s in parsed.sections[:8]:
        parts.append(f"\n## {s.name}\n{s.text}")
    return "\n\n".join(parts)


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_json(text: str) -> list[Any] | None:
    text = _JSON_FENCE_RE.sub("", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "materials" in data:
        inner = data["materials"]
        return inner if isinstance(inner, list) else None
    return None


# Some NER replies stuff units into the number: "150 T", "80-95 K",
# "14.0 GPa", "0.16±0.02". Strip units, take midpoints, drop ± errors.
_RANGE_RE = re.compile(r"^\s*([-+]?\d*\.?\d+)\s*[-–—]\s*([-+]?\d*\.?\d+)")
_NUM_RE   = re.compile(r"[-+]?\d*\.?\d+")


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    # Range — take the midpoint.
    m = _RANGE_RE.match(s)
    if m:
        try:
            return (float(m.group(1)) + float(m.group(2))) / 2
        except (TypeError, ValueError):
            return None
    # Pick the first number in the string — handles "150 T",
    # "14.0 GPa", "0.16 +/- 0.02".
    nm = _NUM_RE.search(s)
    if not nm:
        return None
    try:
        return float(nm.group(0))
    except (TypeError, ValueError):
        return None


def _coerce_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    return None
