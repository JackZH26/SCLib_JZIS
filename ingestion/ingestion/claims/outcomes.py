"""I/O-free negative-outcome shape contract, mirrored in API claim_outcomes.

Canonical inputs use material_claims field names, not raw NER aliases. Passing
this check establishes representability, NOT detection adequacy, source truth,
review approval, Observed origin, pressure applicability, or an ML label policy.
Keep the API and ingestion copies byte-identical; they ship independently.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

OUTCOME_CONTRACT_VERSION = "sclib-claim-outcome/v1"
MISSING_METHODS = frozenset({"", "unknown", "none", "n/a", "not_reported", "not_measured"})
_NONPOSITIVE_STATUSES = frozenset({
    "not_detected", "not_observed", "notdetected", "no_transition", "no_superconductivity",
    "non_superconducting", "negative", "inconclusive", "ambiguous", "uncertain",
    "unknown", "unreported", "non_transition_observed", "refuted",
})


def outcome_conflicts_with_positive(record: Mapping[str, Any]) -> bool:
    """Veto a positive interpretation; this never proves a negative result.

    Inspect every marker rather than selecting the first populated alias. A
    positive result_status must not hide a later negative outcome or boolean.
    Explicit uncertainty/unknown status also cannot become positive from Tc
    alone. Missing markers return False but supply no affirmative evidence.
    """
    for key in ("result_status", "outcome_state", "outcome"):
        value = record.get(key)
        if isinstance(value, str):
            slug = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
            if slug in _NONPOSITIVE_STATUSES:
                return True
    if any(record.get(key) is True for key in ("no_transition", "not_detected")):
        return True
    return any(record.get(key) is False for key in (
        "superconductivity_observed", "transition_observed", "is_superconducting",
    ))


def _finite_nonnegative(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except (OverflowError, ValueError):
        return False


def negative_outcome_issues(claim: Mapping[str, Any]) -> tuple[str, ...]:
    """Return explicit blockers; never infer a negative from missing Tc."""
    issues = []
    if claim.get("result_status") != "not_detected":
        issues.append("negative_result_not_explicit")
    if claim.get("property_type") != "non_transition":
        issues.append("negative_result_property_mismatch")
    relation = claim.get("value_relation")
    value, lower, upper = (claim.get(key) for key in (
        "value_kelvin", "value_lower_kelvin", "value_upper_kelvin",
    ))
    if relation not in {"unreported", "lt", "le"}:
        issues.append("negative_result_conflicts_with_tc_relation")
    elif relation == "unreported":
        if any(item is not None for item in (value, lower, upper)):
            issues.append("negative_result_invalid_value_shape")
    elif value is not None or lower is not None or not _finite_nonnegative(upper):
        issues.append("negative_result_invalid_value_shape")
    if not _finite_nonnegative(claim.get("minimum_temperature_k")):
        issues.append("negative_result_missing_minimum_temperature")
    method = claim.get("measurement_method")
    if not isinstance(method, str) or method.strip().lower() in MISSING_METHODS:
        issues.append("negative_result_missing_measurement_method")
    return tuple(issues)
