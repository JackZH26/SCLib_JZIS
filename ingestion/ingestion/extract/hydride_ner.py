"""Hydride-specific Tc / pressure / Eliashberg parameter NER.

This extractor is intentionally independent from ``material_ner``. The
generic material NER feeds ``papers.materials_extracted`` and the public
``materials`` aggregate; this module targets a narrower scientific need:
for hydrogen-rich superconductors, capture the Tc condition together with
pressure, electron-phonon coupling lambda, Coulomb pseudopotential mu*,
and omega_log.

APS compliance: callers may pass transient APS full text into this module,
but the output must remain derived structured facts only. The prompt asks
for source section names, not quoted evidence snippets, and the validator
does not persist prose.
"""
from __future__ import annotations

import json
import logging
import math
import re
from functools import lru_cache
from typing import Any

from ingestion.extract import formula_validator
from ingestion.models import ParsedPaper

log = logging.getLogger(__name__)

PROMPT_VERSION = "hydride-v1-2026-06-25"
_MAX_CHARS = 32_000

_PROMPT = """\
Extract hydride superconductivity parameters from the paper text below.
Return JSON only, as an array. One object per (material, Tc, pressure,
calculation/measurement condition). Return [] if the paper does not
report hydrogen-rich superconducting materials.

Target compounds:
- metal/sulfur/phosphorus/boron/etc. hydrides and deuterides such as
  H3S, D3S, LaH10, YH6, CaH6, ScH9, LuH3, C-S-H, P/H, SiH4(H2)2.
- The formula must contain H or D plus at least one other element.

Required fields:
- formula: plain text chemical formula, no LaTeX markup.
- tc_kelvin: superconducting Tc in Kelvin for THIS condition.
- pressure_gpa: pressure in GPa for THIS condition. Use null if absent.
- confidence: 0.0-1.0.

Extract these if present for the SAME material/condition:
- lambda_eph: electron-phonon coupling constant lambda.
- mu_star: Coulomb pseudopotential mu* / mu^* / μ* used with Tc.
- omega_log_k: logarithmic average phonon frequency converted to Kelvin.
- omega_log_source_value: raw omega_log number if the paper uses meV,
  cm^-1, THz, or K.
- omega_log_source_unit: "K" | "meV" | "cm^-1" | "THz" | null.
- method: short method tag, e.g. "DFT", "Eliashberg", "Allen-Dynes",
  "McMillan", "resistivity", "susceptibility".
- evidence_type: "primary_theoretical" | "primary_experimental" | "cited".
- source_section: section/table label only, e.g. "Table I",
  "Results", "Supplementary Table S2". Do NOT quote source text.

Rules:
- Do not mix parameters across rows, phases, pressures, or compounds.
  If lambda/mu*/omega_log are listed at 200 GPa and Tc is listed at
  250 GPa, emit separate rows or leave the unmatched fields null.
- Prefer primary values produced in this paper. If a value is only in
  the introduction, comparison text, or a cited benchmark table, mark
  evidence_type="cited".
- If omega_log is in meV, cm^-1, or THz, still emit omega_log_k converted
  to Kelvin using:
  meV * 11.6045, cm^-1 * 1.43877, THz * 47.9924.
- Extract numerical values only. If a range is reported, use the midpoint.
- Do not invent missing mu*. If the paper says "mu*=0.10" or "μ*=0.13",
  emit that exact number.
- Do not emit evidence quotes or full sentences.

Text:
---
{{BODY}}
---
"""

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_RANGE_RE = re.compile(r"^\s*([-+]?\d*\.?\d+)\s*[-–—]\s*([-+]?\d*\.?\d+)")
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")
_ELEMENT_RE = re.compile(r"[A-Z][a-z]?")
_OMEGA_UNIT_ALIASES = {
    "k": "K",
    "kelvin": "K",
    "mev": "meV",
    "cm-1": "cm^-1",
    "cm^-1": "cm^-1",
    "cm−1": "cm^-1",
    "cm⁻¹": "cm^-1",
    "thz": "THz",
}


@lru_cache(maxsize=1)
def _client() -> Any:
    from ingestion.genai_client import make_genai_client

    return make_genai_client()


def extract_hydride_parameters(parsed: ParsedPaper) -> list[dict[str, Any]]:
    """Run hydride-specific NER and return cleaned structured records."""
    from ingestion.config import get_settings

    settings = get_settings()
    body = _assemble_text(parsed)
    if not body.strip():
        return []

    prompt = _PROMPT.replace("{{BODY}}", body[:_MAX_CHARS])
    try:
        from google.genai import types as genai_types

        resp = _client().models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("%s: hydride NER call failed: %s", parsed.meta.paper_id, e)
        return []

    records = _parse_json((resp.text or "").strip())
    if records is None:
        log.warning("%s: hydride NER returned non-JSON", parsed.meta.paper_id)
        return []

    cleaned: list[dict[str, Any]] = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        record = clean_hydride_record(raw, model=settings.gemini_model)
        if record is not None:
            cleaned.append(record)
    return cleaned


def clean_hydride_record(
    raw: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any] | None:
    """Coerce, validate, and range-gate one raw NER record.

    Returns None for records that should not be persisted. Non-fatal
    scientific consistency concerns are kept in ``validation_flags``.
    """
    formula = _normalize_formula_text(str(raw.get("formula") or ""))
    formula = formula_validator.normalize_whitespace(formula)
    ok, reject_reason = formula_validator.validate_formula(formula)
    if not ok:
        log.debug("dropping hydride NER formula=%r reason=%s", formula, reject_reason)
        return None
    if not _looks_like_hydride(formula):
        log.debug("dropping non-hydride formula from hydride NER: %r", formula)
        return None

    tc = _coerce_float(raw.get("tc_kelvin"))
    if tc is None or not (0.01 <= tc <= 400.0):
        return None

    pressure = _coerce_float(raw.get("pressure_gpa"))
    lambda_eph = _coerce_float(raw.get("lambda_eph"))
    mu_star = _coerce_float(raw.get("mu_star"))
    omega_raw = _coerce_float(raw.get("omega_log_source_value"))
    omega_unit = _normalize_unit(raw.get("omega_log_source_unit"))
    omega_log_k = _coerce_float(raw.get("omega_log_k"))
    if omega_log_k is None and omega_raw is not None:
        omega_log_k = _convert_omega_to_k(omega_raw, omega_unit)

    flags: list[str] = []
    if pressure is not None and not (0.0 <= pressure <= 500.0):
        return None
    if lambda_eph is not None and not (0.01 <= lambda_eph <= 10.0):
        return None
    if mu_star is not None and not (0.0 <= mu_star <= 0.5):
        return None
    if omega_log_k is not None and not (1.0 <= omega_log_k <= 5000.0):
        return None

    if all(v is None for v in (pressure, lambda_eph, mu_star, omega_log_k)):
        # This table is for condition parameters, not a second generic Tc list.
        return None

    confidence = _coerce_float(raw.get("confidence"))
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))

    provenance: dict[str, Any] = {}
    if omega_raw is not None or omega_unit is not None:
        provenance["omega_log_raw"] = {
            "value": omega_raw,
            "unit": omega_unit,
        }
    _add_allen_dynes_check(
        flags,
        provenance,
        tc_kelvin=tc,
        lambda_eph=lambda_eph,
        mu_star=mu_star,
        omega_log_k=omega_log_k,
    )

    normalized = _normalize_formula_for_storage(formula)
    method = _clip_str(raw.get("method"), 80)
    evidence_type = _normalize_evidence_type(raw.get("evidence_type"))
    source_section = _clip_str(raw.get("source_section"), 200)

    return {
        "formula": formula,
        "formula_normalized": normalized,
        "tc_kelvin": tc,
        "pressure_gpa": pressure,
        "lambda_eph": lambda_eph,
        "mu_star": mu_star,
        "omega_log_k": omega_log_k,
        "omega_log_source_value": omega_raw,
        "omega_log_source_unit": omega_unit,
        "method": method,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "source_section": source_section,
        "validation_flags": flags,
        "provenance": provenance,
        "model": model,
        "prompt_version": PROMPT_VERSION,
    }


def _assemble_text(parsed: ParsedPaper) -> str:
    parts = [f"Title: {parsed.meta.title}", f"Abstract: {parsed.meta.abstract}"]
    for s in parsed.sections[:16]:
        parts.append(f"\n## {s.name}\n{s.text}")
    return "\n\n".join(parts)


def _parse_json(text: str) -> list[Any] | None:
    text = _JSON_FENCE_RE.sub("", text).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("hydride_parameters", "parameters", "records", "materials"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return None


def _normalize_formula_text(raw: str) -> str:
    table = str.maketrans(
        "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕₖₗₘₙₒₚₛₜₓ",
        "0123456789+-=()aehklmnopstx",
    )
    raw = raw.translate(table)
    raw = raw.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾", "0123456789+-=()"))
    raw = raw.replace("−", "-")
    raw = raw.replace("\\mathrm", "")
    raw = re.sub(r"[\$_{}\\]", "", raw).strip()
    if (
        re.fullmatch(r"(?:[A-Z][a-z]?[-·]){1,}[A-Z][a-z]?", raw)
        and re.search(r"(?:^|[-·])[HD](?:$|[-·])", raw)
    ):
        raw = raw.replace("-", "").replace("·", "")
    return raw


def _looks_like_hydride(formula: str) -> bool:
    elements = set(_ELEMENT_RE.findall(formula))
    has_hydrogen = "H" in elements or "D" in elements
    partners = elements - {"H", "D"}
    return has_hydrogen and bool(partners)


def _normalize_formula_for_storage(formula: str) -> str:
    try:
        from ingestion.nims import normalize_formula
    except Exception:  # noqa: BLE001 - keep post-processing unit-testable without DB deps
        return formula
    return normalize_formula(formula)


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    s = str(value).strip()
    if not s:
        return None
    m = _RANGE_RE.match(s)
    if m:
        try:
            return (float(m.group(1)) + float(m.group(2))) / 2
        except (TypeError, ValueError):
            return None
    nm = _NUM_RE.search(s)
    if not nm:
        return None
    try:
        v = float(nm.group(0))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _normalize_unit(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    key = (
        raw.lower()
        .replace(" ", "")
        .replace("−", "-")
        .replace("^-1", "^-1")
    )
    return _OMEGA_UNIT_ALIASES.get(key, raw[:20])


def _convert_omega_to_k(value: float, unit: str | None) -> float | None:
    if unit == "K" or unit is None:
        return value
    if unit == "meV":
        return value * 11.6045
    if unit == "cm^-1":
        return value * 1.43877
    if unit == "THz":
        return value * 47.9924
    return None


def _normalize_evidence_type(value: Any) -> str | None:
    if value is None:
        return None
    ev = str(value).strip().lower()
    allowed = {"primary_theoretical", "primary_experimental", "cited"}
    return ev if ev in allowed else None


def _clip_str(value: Any, max_len: int) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]


def _add_allen_dynes_check(
    flags: list[str],
    provenance: dict[str, Any],
    *,
    tc_kelvin: float,
    lambda_eph: float | None,
    mu_star: float | None,
    omega_log_k: float | None,
) -> None:
    if lambda_eph is None or mu_star is None or omega_log_k is None:
        return
    denom = lambda_eph - mu_star * (1.0 + 0.62 * lambda_eph)
    if denom <= 0:
        flags.append("allen_dynes_denominator_nonpositive")
        return
    exponent = -1.04 * (1.0 + lambda_eph) / denom
    try:
        tc_est = (omega_log_k / 1.2) * math.exp(exponent)
    except OverflowError:
        flags.append("allen_dynes_overflow")
        return
    provenance["allen_dynes_tc_k"] = round(tc_est, 3)
    if tc_kelvin > 0:
        rel = abs(tc_est - tc_kelvin) / max(tc_kelvin, 1.0)
        provenance["allen_dynes_relative_error"] = round(rel, 3)
        if rel > 0.6:
            flags.append("allen_dynes_mismatch")
