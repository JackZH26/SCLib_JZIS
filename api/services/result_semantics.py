"""Versioned, I/O-free result-origin contract shared by API and ingestion.

Canonical source: ingestion/ingestion/result_semantics.py. The API vendors an
identical copy because the two images have independent build contexts. A
byte-parity test is a release gate; edit both copies together.

This classifies reported knowledge, NOT scientific validity, independent
replication, superconductivity detection, or applicability to another state.
Paper genre, pressure, source tier and extractor identity are never evidence
that an individual result was experimentally measured.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

CLASSIFIER_VERSION = "sclib-result-origin/v1"
ORIGINS = ("Observed", "Computed", "Inferred", "AI-Proposed", "Unknown")

_ORIGIN_ALIASES = {
    "observed": "Observed", "experimental": "Observed", "experiment": "Observed",
    "measured": "Observed", "primary_experimental": "Observed",
    "computed": "Computed", "computational": "Computed", "theoretical": "Computed",
    "theory": "Computed", "calculated": "Computed", "primary_theoretical": "Computed",
    "inferred": "Inferred", "physics_prior": "Inferred", "family_prior": "Inferred",
    "ai_proposed": "AI-Proposed", "llm_generated_hypothesis": "AI-Proposed",
}
_ROLE_ALIASES = {
    "primary": "primary", "primary_result": "primary",
    "primary_experimental": "primary", "primary_theoretical": "primary",
    "cited": "cited", "cited_prior_work": "cited", "secondary": "cited",
    "citation": "cited", "referenced": "cited",
}
_OBSERVED_METHODS = frozenset({
    "resistivity", "resistance", "resistive", "electrical_resistivity",
    "susceptibility", "magnetic_susceptibility", "ac_susceptibility", "dc_susceptibility",
    "specific_heat", "heat_capacity", "specific_heat_capacity",
    "arpes", "musr", "mu_sr", "muon_spin_rotation", "muon_spin_relaxation",
    "stm", "neutron", "nmr", "nqr", "magnetization", "thermal_conductivity",
    "raman_scattering", "raman", "andreev_reflection", "nernst", "tunneling",
    "esr", "torque_magnetometry", "hall_effect", "transport", "electrical_transport",
})
_COMPUTED_METHODS = frozenset({
    "calculation", "dft", "dfpt", "first_principles", "first_principle",
    "first_principles_calculation", "computational", "ab_initio", "abinitio",
    "density_functional_theory", "allen_dynes", "allen_dynes_calculation",
    "eliashberg", "tight_binding", "scdft",
})


def _slug(value: Any) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().lower()) if isinstance(value, str) else ""


@dataclass(frozen=True, slots=True)
class ResultClassification:
    knowledge_origin: str
    classification_status: str
    source_role: str
    reasons: tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "knowledge_origin": self.knowledge_origin,
            "classification_status": self.classification_status,
            "source_role": self.source_role,
            "classification_reasons": list(self.reasons),
            "classifier_version": self.classifier_version,
        }


def classify_result(record: Mapping[str, Any]) -> ResultClassification:
    """Resolve only explicit result-level labels/methods; conflicts fail closed.

    Legacy 'primary'/'cited' supplies role, not origin. 'primary_experimental'
    and 'primary_theoretical' supply both axes. Generic 'predicted' is
    ambiguous (a calculation, inference or generated hypothesis), hence unknown.
    An extraction_method='LLM' never makes an observed result AI-Proposed.
    Previously derived annotations are not fed back as fresh evidence.
    """
    origins: set[str] = set()
    roles: set[str] = set()
    reasons: set[str] = set()
    # annotate_record wraps the derived envelope rather than overwriting raw
    # fields, so existing explicit knowledge_origin/source_role remain inputs.
    for key in ("knowledge_origin", "result_origin", "evidence_role", "evidence_type", "claim_kind"):
        value = _slug(record.get(key))
        if value in _ORIGIN_ALIASES:
            origins.add(_ORIGIN_ALIASES[value])
            reasons.add("origin_label:" + key)
        if value in _ROLE_ALIASES:
            roles.add(_ROLE_ALIASES[value])
    role = _slug(record.get("source_role"))
    if role in _ROLE_ALIASES:
        roles.add(_ROLE_ALIASES[role])
    for key in ("measurement", "measurement_method", "method"):
        value = _slug(record.get(key))
        if value in _OBSERVED_METHODS:
            origins.add("Observed")
            reasons.add("observed_method:" + key)
        elif value in _COMPUTED_METHODS:
            origins.add("Computed")
            reasons.add("computed_method:" + key)
    if len(origins) > 1:
        origin, status = "Unknown", "conflicted"
        reasons.add("conflicting_result_origins")
    elif origins:
        origin, status = next(iter(origins)), "resolved"
    else:
        origin, status = "Unknown", "unknown"
        reasons.add("missing_result_origin")
        if record.get("paper_type"):
            reasons.add("paper_type_is_not_result_evidence")
    if len(roles) > 1:
        resolved_role = "conflicted"
        reasons.add("conflicting_source_roles")
    elif roles:
        resolved_role = next(iter(roles))
    else:
        resolved_role = "unknown"
        reasons.add("missing_source_role")
    return ResultClassification(origin, status, resolved_role, tuple(sorted(reasons)))


def annotate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with a derived envelope; do not overwrite raw assertions."""
    return {**record, "result_classification": classify_result(record).as_dict()}


def annotate_records(records: Any) -> list[dict[str, Any]]:
    return [annotate_record(r) for r in records or [] if isinstance(r, Mapping)]


def evidence_classifications(records: Any) -> list[dict[str, Any]]:
    """Bounded metadata for citations/prompts, not an arbitrary nested-record export.

    The source excerpt carries scientific values. Only an optional formula and
    derived policy labels are added here; raw extraction/provenance/reviewer
    payloads are never copied into this new public field.
    """
    result = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        item: dict[str, Any] = {"result_classification": classify_result(record).as_dict()}
        formula = record.get("formula")
        if isinstance(formula, str) and 0 < len(formula) <= 200:
            item["formula"] = formula
        result.append(item)
        if len(result) == 50:
            break
    return result


def is_observed_result(record: Mapping[str, Any]) -> bool:
    result = classify_result(record)
    return (
        result.knowledge_origin == "Observed"
        and result.classification_status == "resolved"
        and result.source_role != "conflicted"
    )


def is_computed_result(record: Mapping[str, Any]) -> bool:
    result = classify_result(record)
    return (
        result.knowledge_origin == "Computed"
        and result.classification_status == "resolved"
        and result.source_role != "conflicted"
    )


def legacy_evidence_role(record: Mapping[str, Any]) -> str:
    """Conservative adapter for v1's combined enum; preserve both axes elsewhere."""
    result = classify_result(record)
    if result.source_role == "cited":
        return "cited"
    if result.source_role != "primary" or result.classification_status != "resolved":
        return "unknown"
    return {"Observed": "primary_experimental", "Computed": "primary_theoretical"}.get(
        result.knowledge_origin, "unknown"
    )


def classification_summary(records: Any) -> dict[str, Any]:
    counts = dict.fromkeys(ORIGINS, 0)
    conflicts = 0
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        result = classify_result(record)
        counts[result.knowledge_origin] += 1
        conflicts += int(result.classification_status == "conflicted" or result.source_role == "conflicted")
    return {"classifier_version": CLASSIFIER_VERSION, "origin_counts": counts, "conflicted_records": conflicts}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def headline_origin(records: Any, value: Any) -> str:
    """Label a legacy headline only when its matching result origins agree.

    This is an origin display check, NOT an approval of aggregate selection
    or atomic state attribution (separate SC02/SC03 work).
    """
    value = _finite_number(value)
    if value is None:
        return "Unknown"
    origins: set[str] = set()
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        tc = _finite_number(record.get("tc_kelvin"))
        if tc is None:
            continue
        if tc == value:
            result = classify_result(record)
            origins.add(result.knowledge_origin if result.source_role != "conflicted" else "Unknown")
    return next(iter(origins)) if len(origins) == 1 else "Unknown"


def checked_legacy_split(records: Any, value: Any, origin: str) -> float | None:
    """Only retain a stored split value supported by the current origin policy.

    No new maximum is manufactured and no database value is overwritten. This
    is a display compatibility check, not an accepted-result/SC02 selection.
    """
    value = _finite_number(value)
    if value is None:
        return None
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        result = classify_result(record)
        if (_finite_number(record.get("tc_kelvin")) == value
                and result.knowledge_origin == origin
                and result.classification_status == "resolved"
                and result.source_role != "conflicted"
                and (origin != "Observed" or result.source_role != "cited")):
            return float(value)
    return None


def evidence_summary(records: Any) -> str | None:
    classifications = [classify_result(r) for r in records or [] if isinstance(r, Mapping)]
    primary_origins = {
        c.knowledge_origin for c in classifications
        if c.source_role not in {"cited", "conflicted"} and c.classification_status == "resolved"
    }
    if {"Observed", "Computed"}.issubset(primary_origins):
        return "mixed"
    if "Observed" in primary_origins:
        return "experimental"
    if "Computed" in primary_origins:
        return "theoretical"
    if classifications and all(c.source_role == "cited" for c in classifications):
        return "cited_only"
    return None
