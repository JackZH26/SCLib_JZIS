"""Atomic, bounded property evidence for legacy catalog displays, without I/O.

This is a provenance projection, not adjudication or a joint ML observation.
Supply an existing summary to preserve its value policy without reviving values
that an older cap, override or visibility policy omitted.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .pressure_semantics import classify_pressure
from .result_semantics import classify_result

# Both deployment packages vendor the same bytes but have independent layouts.
if __package__ == "ingestion":
    from .claims.outcomes import outcome_conflicts_with_positive
    from .extract.scientific_values import record_quantity
else:
    from .claim_outcomes import outcome_conflicts_with_positive
    from .scientific_values import record_quantity

PROPERTY_EVIDENCE_VERSION = "property-evidence/1.1.0"
ATOMIC_SELECTION_POLICY = "atomic-anomaly-aggregation/1.0.0"
EVIDENCE_LIMIT = 20
EPC_COMPARISON_BUDGET = 10_000
DERIVED_ENVELOPES = frozenset({"result_classification", "pressure_semantics", "property_evidence", "anomaly_review", "visibility", "structure_evidence", "ingestion_capture", "temporal_provenance"})
NUMERIC_PROPERTIES = {
    "tc_max": "tc_kelvin",
    "tc_max_experimental": "tc_kelvin",
    "tc_max_theoretical": "tc_kelvin",
    "tc_ambient": "tc_kelvin",
    "hc2_tesla": "hc2_tesla",
    "lambda_eph": "lambda_eph",
    "omega_log_k": "omega_log_k",
    "rho_s_mev": "rho_s_mev",
    "t_cdw_k": "t_cdw_k",
    "t_sdw_k": "t_sdw_k",
    "t_afm_k": "t_afm_k",
    "rho_exponent": "rho_exponent",
    "doping_level": "doping_level",
    "lambda_london_nm": "lambda_london_nm",
    "xi_gl_nm": "xi_gl_nm",
    "layer_thickness_nm": "layer_thickness_nm",
}
CATEGORICAL_PROPERTIES = (
    "crystal_structure", "space_group", "structure_phase", "pairing_symmetry",
    "gap_structure", "competing_order", "sample_form", "substrate",
    "pressure_type", "doping_type", "formula_substrate", "formula_overlayer",
    "is_unconventional", "has_competing_order",
)
PROPERTY_FIELDS = tuple(NUMERIC_PROPERTIES) + CATEGORICAL_PROPERTIES + ("lattice_params",)
MEDIAN_PROPERTIES = frozenset({"rho_exponent", "doping_level"})
_LATTICE_FIELDS = ("a", "b", "c", "alpha", "beta", "gamma")
_CONDITION_TEXT = (
    "hc2_conditions", "tc_conditions", "tc_type", "tc_criterion", "hc2_direction",
    "field_orientation", "magnetic_field_orientation", "method", "measurement", "measurement_method",
    "calculation_method", "protocol_id", "calculation_protocol",
)
_TEMPERATURE_FIELDS = ("temperature_k", "measurement_temperature_k", "hc2_temperature_k")
_LOCATOR_FIELDS = ("page", "table", "figure", "row", "column", "section", "chunk_id", "span_id")
_MISSING = frozenset({"", "unknown", "none", "null", "n/a", "not_reported", "unspecified"})
_QUANTITY_FIELDS = (
    "status", "relation", "value_kind", "value", "lower", "upper", "unit",
    "uncertainty", "uncertainty_interpretation", "approximate", "raw_value",
    "raw_unit", "unit_basis", "errors", "parser_version", "proposal_hash",
)


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def _text(value: Any, limit: int = 240) -> str | None:
    """Oversize text is omitted, never truncated into a different identifier."""
    if not isinstance(value, str) or len(value) > limit:
        return None
    return value if value.strip().lower() not in _MISSING else None


def _public_raw(value: Any) -> Any:
    if value is None or isinstance(value, bool) or _finite(value):
        return value
    if isinstance(value, str) and len(value) <= 256:
        return value
    if isinstance(value, (list, tuple)) and len(value) <= 2:
        return [_public_raw(item) for item in value]
    # Do not expose arbitrary nested private fields, including a malformed
    # proposal archived as raw_value by the numeric parser.
    encoded = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    return {"redacted": "structured_or_oversize_raw", "sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def _quantity(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (_public_raw(value.get(key)) if key == "raw_value" else
              _text(value.get(key), 40) if key == "raw_unit" else
              list(value.get(key) or []) if key == "errors" else value.get(key))
        for key in _QUANTITY_FIELDS
    }


def _number(record: Mapping[str, Any], field: str) -> dict[str, Any]:
    return record_quantity(record, field, *(("tc",) if field == "tc_kelvin" else ()))


def _point(value: Mapping[str, Any]) -> float | None:
    number = value.get("value")
    return float(number) if value.get("status") == "parsed" and not value.get("errors") and value.get("relation") == "exact" and _finite(number) else None


def _locator(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item for key in _LOCATOR_FIELDS
        if (item := value.get(key)) is not None
        and (isinstance(item, int) and not isinstance(item, bool) or _text(item, 120) is not None)
    }


def legacy_result_id(record: Mapping[str, Any], *, scope_id: str) -> str:
    """Same scope+raw-content identity used by scientific search references."""
    original = {key: value for key, value in record.items() if key not in DERIVED_ENVELOPES}
    payload = json.dumps([scope_id, original], sort_keys=True, separators=(",", ":"), default=str)
    return "legacy-result:" + hashlib.sha256(payload.encode()).hexdigest()


def _pressure(record: Mapping[str, Any]) -> dict[str, Any]:
    value = classify_pressure(record).to_dict()
    value["raw_value"] = _public_raw(value["raw_value"])
    value["raw_unit"] = _text(value["raw_unit"], 40)
    value["source_locator"] = _locator(value["source_locator"])
    return value


def _structure(record: Mapping[str, Any]) -> dict[str, Any]:
    quantities = {}
    nested = record.get("lattice_params")
    for component in _LATTICE_FIELDS:
        field = "lattice_" + component
        source = record
        if record.get(field) is None and isinstance(nested, Mapping) and component in nested:
            # Same record only. Preserve a typed proposal in preference to the
            # nested compatibility value; never borrow another record's cell.
            source = {**record, field: nested[component]}
            if "unit" in nested:
                source = {**source, field + "_unit": nested["unit"]}
        proposal = _number(source, field)
        if proposal["status"] != "unreported":
            quantities[component] = _quantity(proposal)
    lattice = {component: value for component, proposal in quantities.items() if (value := _point(proposal)) is not None}
    return {
        **{key: _text(record.get(key)) for key in ("crystal_structure", "space_group", "structure_phase")},
        "lattice_params": lattice or None,
        "lattice_quantities": quantities,
    }


def _base(record: Mapping[str, Any], scope_id: str) -> dict[str, Any]:
    conditions = {key: _text(record.get(key)) for key in _CONDITION_TEXT}
    for field in _TEMPERATURE_FIELDS:
        proposal = _number(record, field)
        conditions[field] = _quantity(proposal) if proposal["status"] != "unreported" else None
    doping = _number(record, "doping_level")
    return {
        "result_id": legacy_result_id(record, scope_id=scope_id),
        "conditions": conditions,
        "state": {
            **{key: _text(record.get(key), 160) for key in ("state_id", "structure_id", "sample_id", "run_id")},
            # Display the selected occurrence's composition notation only.
            # Neither summary fallback nor string equality establishes identity.
            **{key: _text(record.get(key), 200) for key in ("formula", "formula_raw")},
            "pressure_semantics": _pressure(record),
            **{key: _text(record.get(key)) for key in ("sample_form", "substrate", "doping_type")},
            "doping_level": _quantity(doping) if doping["status"] != "unreported" else None,
        },
        "source": {
            **{key: _text(record.get(key), 200) for key in ("paper_id", "doi", "arxiv_id")},
            "year": record.get("year") if isinstance(record.get("year"), int) and not isinstance(record.get("year"), bool) else None,
            "source_locator": _locator(record.get("source_locator")),
        },
        "origin": classify_result(record).as_dict(),
        "structure": _structure(record),
    }


def _origin_matches(base: Mapping[str, Any], origin: str) -> bool:
    value = base["origin"]
    return value["knowledge_origin"] == origin and value["classification_status"] == "resolved" and value["source_role"] != "conflicted"


def _candidate(record: Mapping[str, Any], base: dict[str, Any], field: str) -> dict[str, Any] | None:
    warnings = []
    if not base["source"]["paper_id"] and not base["source"]["doi"] and not base["source"]["arxiv_id"]:
        warnings.append("source_work_not_reported")
    if not base["state"]["state_id"] or not base["state"]["structure_id"]:
        warnings.append("state_structure_association_incomplete")
    if not any(base["conditions"][key] for key in ("method", "measurement", "measurement_method", "calculation_method")):
        warnings.append("method_not_reported")
    if base["origin"]["classification_status"] == "conflicted" or base["origin"]["source_role"] == "conflicted":
        warnings.append("result_classification_conflicted")
    quantity = None
    if field in NUMERIC_PROPERTIES:
        proposal = _number(record, NUMERIC_PROPERTIES[field])
        if proposal["status"] == "unreported":
            return None
        quantity = _quantity(proposal)
        base = {**base, "source": {**base["source"], "source_locator": _locator(proposal.get("source_locator"))}}
        value = _point(proposal)
        if field.startswith("tc_"):
            if outcome_conflicts_with_positive(record):
                warnings.append("outcome_does_not_support_positive_tc")
            if value is not None and value <= 0:
                warnings.append("nonpositive_tc_not_positive_headline")
            required_origin = {"tc_max_experimental": "Observed", "tc_max_theoretical": "Computed", "tc_ambient": "Observed"}.get(field)
            if required_origin and not _origin_matches(base, required_origin):
                warnings.append("result_origin_not_supported")
            if field == "tc_ambient" and base["state"]["pressure_semantics"]["pressure_state"] != "explicit_ambient":
                warnings.append("ambient_pressure_not_explicit")
        if value is None:
            warnings.append("no_compatible_point_value")
        if proposal["approximate"]:
            warnings.append("approximate_point_not_exact_precision")
        if proposal["uncertainty"] is not None:
            warnings.append("reported_uncertainty_not_exact_precision")
    elif field == "lattice_params":
        value = base["structure"]["lattice_params"]
        if not base["structure"]["lattice_quantities"]:
            return None
        quantity = {"status": "parsed" if value is not None else "invalid", "relation": "group",
                    "components": base["structure"]["lattice_quantities"]}
        if value is None:
            warnings.append("no_compatible_point_value")
    else:
        value = record.get(field)
        if not isinstance(value, bool):
            value = _text(value)
        if value is None:
            return None
    return {**base, "property": field, "value": value, "quantity": quantity, "warnings": warnings}


def _eligible(candidate: Mapping[str, Any]) -> bool:
    return candidate["value"] is not None and not any(
        reason in candidate["warnings"] for reason in (
            "outcome_does_not_support_positive_tc", "nonpositive_tc_not_positive_headline",
            "result_origin_not_supported", "ambient_pressure_not_explicit",
            "no_compatible_point_value", "anomaly_review_required",
        )
    )


def _supports(candidate: Mapping[str, Any], legacy: Any, field: str) -> bool:
    if not _eligible(candidate):
        return False
    value = candidate["value"]
    if field == "lattice_params":
        return isinstance(legacy, Mapping) and bool(legacy) and all(
            key in _LATTICE_FIELDS and _finite(item) and value.get(key) == item
            for key, item in legacy.items()
        )
    if field in NUMERIC_PROPERTIES:
        return _finite(legacy) and value == legacy
    return type(value) is type(legacy) and value == legacy


def _default_key(candidate: Mapping[str, Any], field: str) -> tuple:
    # No medians/modes are manufactured. Max fields use the reported center,
    # then stable raw-content identity; categorical/median views pick one source.
    value = candidate["value"]
    maximum = -value if field in NUMERIC_PROPERTIES and field not in MEDIAN_PROPERTIES and _finite(value) else 0
    return maximum, candidate["result_id"]


def _property(
    field: str, candidates: list[dict[str, Any]], legacy: Mapping[str, Any] | None,
    selection_policy: str | None = None,
) -> dict[str, Any]:
    candidates = sorted(candidates, key=lambda item: item["result_id"])
    warnings = []
    selected = None
    selection = "none"
    if legacy is not None:
        expected = legacy.get(field)
        if expected is None:
            status = "not_reported"
            if candidates:
                warnings.append("legacy_summary_missing_not_recomputed")
        else:
            supported = [item for item in candidates if _supports(item, expected, field)]
            if field == "tc_max":
                # The legacy headline preferred the experimental pool. Equal
                # Computed values do not become its source merely by hash order.
                experimental = legacy.get("tc_max_experimental")
                theoretical = legacy.get("tc_max_theoretical")
                if selection_policy == ATOMIC_SELECTION_POLICY:
                    # Only newly versioned aggregation certifies this policy.
                    # A view-specific reference can make headline and split
                    # values differ; use the eligible headline origin pool.
                    pool_origin = next((origin for origin in ("Observed", "Computed") if any(
                        _eligible(item) and _origin_matches(item, origin) for item in candidates
                    )), None)
                    supported = [item for item in supported if pool_origin and _origin_matches(item, pool_origin)]
                    if not supported:
                        warnings.append("current_origin_pool_untraceable")
                elif _finite(experimental) and experimental == expected:
                    supported = [item for item in supported if _origin_matches(item, "Observed")]
                    if not supported:
                        warnings.append("legacy_origin_pool_untraceable")
                elif experimental is None and _finite(theoretical) and theoretical == expected:
                    supported = [item for item in supported if _origin_matches(item, "Computed")]
                    if not supported:
                        warnings.append("legacy_origin_pool_untraceable")
                elif _finite(experimental) or _finite(theoretical):
                    supported = []
                    warnings.append("legacy_origin_pool_untraceable")
            if supported:
                selected = deepcopy(supported[0])
                if field == "lattice_params":
                    selected["value"] = dict(expected)
                status, selection = "supported", "legacy_exact_support"
            else:
                status = "untraceable"
                warnings.append("legacy_summary_has_no_exact_source_support")
    else:
        supported = [item for item in candidates if _eligible(item)]
        if supported:
            selected = deepcopy(min(supported, key=lambda item: _default_key(item, field)))
            status, selection = "supported", "deterministic_result"
        else:
            status = "pending" if candidates else "not_reported"
    if field in MEDIAN_PROPERTIES and legacy is not None:
        warnings.append("catalogue_statistic_not_joint_observation")
    if selected is None and any("anomaly_review_required" in item["warnings"] for item in candidates):
        warnings.append("anomaly_review_required")
    if selected is not None:
        warnings.extend(selected["warnings"])
        # Keep the selected result visible even if it sorts beyond the cap.
        evidence = [selected] + [item for item in candidates if item["result_id"] != selected["result_id"]]
    else:
        evidence = candidates
    return {
        "status": status, "selection": selection, "selected": selected,
        "evidence": evidence[:EVIDENCE_LIMIT], "total_evidence_count": len(candidates),
        "truncated": len(evidence) > EVIDENCE_LIMIT,
        "warnings": sorted(set(warnings)),
        "statistic": "catalogue_median" if field in MEDIAN_PROPERTIES and legacy is not None else None,
    }


def _epc_key(candidate: Mapping[str, Any]) -> tuple | None:
    if not _joint_state_eligible(candidate):
        return None
    state, conditions = candidate["state"], candidate["conditions"]
    identifiers = tuple(state[key] for key in ("state_id", "structure_id", "run_id"))
    protocol = conditions["protocol_id"] or conditions["calculation_protocol"]
    method = conditions["calculation_method"] or conditions["method"] or conditions["measurement"]
    if not all(identifiers) or not protocol or not method or not _origin_matches(candidate, "Computed"):
        return None
    if conditions["protocol_id"] and conditions["calculation_protocol"] and conditions["protocol_id"] != conditions["calculation_protocol"]:
        return None
    if state["pressure_semantics"]["pressure_state"] == "ambiguous":
        return None
    if candidate["quantity"].get("approximate") or candidate["quantity"].get("uncertainty") is not None:
        return None
    return (*identifiers, protocol, method)


def _joint_state_eligible(candidate: Mapping[str, Any]) -> bool:
    from .anomaly_review import eligible_for_property

    assessment = candidate.get("anomaly_review")
    return isinstance(assessment, Mapping) and all(
        eligible_for_property(assessment, field)
        for field in ("pressure_gpa", "lattice_params", "doping_level", *_TEMPERATURE_FIELDS)
    )


def _state_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    for field in ("state_id", "structure_id", "run_id", "sample_id", "sample_form", "substrate", "doping_type"):
        a, b = left["state"][field], right["state"][field]
        if a is not None and b is not None and a != b:
            return True
    # Complete explicit identity is required above; it never licenses ignoring
    # contradictory known pressure or crystal evidence.
    a, b = left["state"]["pressure_semantics"], right["state"]["pressure_semantics"]
    if a["pressure_state"] == "ambiguous" or b["pressure_state"] == "ambiguous":
        return True
    if a["pressure_state"] in {"reported", "explicit_ambient"} and b["pressure_state"] in {"reported", "explicit_ambient"}:
        keys = ("relation", "pressure_gpa", "value_lower_gpa", "value_upper_gpa", "uncertainty_gpa")
        if any(a[key] != b[key] for key in keys):
            return True
    for key in ("crystal_structure", "space_group", "structure_phase"):
        a, b = left["structure"][key], right["structure"][key]
        if a is not None and b is not None and a != b:
            return True
    quantity_pairs = [(left["state"]["doping_level"], right["state"]["doping_level"])]
    quantity_pairs.extend((left["conditions"][key], right["conditions"][key]) for key in _TEMPERATURE_FIELDS)
    common_lattice = left["structure"]["lattice_quantities"].keys() & right["structure"]["lattice_quantities"].keys()
    quantity_pairs.extend((left["structure"]["lattice_quantities"][key], right["structure"]["lattice_quantities"][key]) for key in common_lattice)
    for a, b in quantity_pairs:
        if any(isinstance(item, Mapping) and item.get("status") == "invalid" for item in (a, b)):
            return True
        if not isinstance(a, Mapping) or not isinstance(b, Mapping) or a.get("status") != "parsed" or b.get("status") != "parsed":
            continue
        if any(a.get(key) != b.get(key) for key in ("relation", "value", "lower", "upper", "uncertainty", "approximate")):
            return True
    return False


def _review_matches(review: Any, left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if not _joint_state_eligible(left) or not _joint_state_eligible(right):
        return False
    if not isinstance(review, Mapping) or review.get("status") != "accepted":
        return False
    if not all(_text(review.get(key), 160) for key in ("review_id", "review_revision", "state_id", "structure_id", "protocol_id")):
        return False
    ids = review.get("result_ids")
    if not isinstance(ids, (list, tuple)) or len(ids) not in {1, 2} or not all(_text(item, 160) for item in ids):
        return False
    for candidate in (left, right):
        for key in ("state_id", "structure_id"):
            known = candidate["state"][key]
            if known is not None and known != review[key]:
                return False
        for key in ("protocol_id", "calculation_protocol"):
            protocol = candidate["conditions"][key]
            if protocol is not None and protocol != review["protocol_id"]:
                return False
    return (isinstance(ids, (list, tuple)) and len(ids) in {1, 2}
            and set(ids) == {left["result_id"], right["result_id"]}
            and _origin_matches(left, "Computed") and _origin_matches(right, "Computed")
            and not _state_conflict(left, right))


def _joint_epc(
    candidates: Mapping[str, list[dict[str, Any]]], reviews: Sequence[Any],
    legacy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    lambdas = [item for item in candidates["lambda_eph"] if _eligible(item) and item["value"] > 0]
    omegas = [item for item in candidates["omega_log_k"] if _eligible(item) and item["value"] > 0]
    if legacy is not None:
        lambdas = [item for item in lambdas if _supports(item, legacy.get("lambda_eph"), "lambda_eph")]
        omegas = [item for item in omegas if _supports(item, legacy.get("omega_log_k"), "omega_log_k")]
    # Index explicit associations before pairing. Unrelated states never enter
    # a Cartesian product. Even one huge same-run group has a documented cap.
    omegas_by_key: dict[tuple, list[dict[str, Any]]] = {}
    omega_by_id = {item["result_id"]: item for item in omegas}
    for item in omegas:
        key = _epc_key(item)
        if key is not None:
            omegas_by_key.setdefault(key, []).append(item)
    reviews_by_result: dict[str, list[Mapping[str, Any]]] = {}
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        ids = review.get("result_ids")
        if not isinstance(ids, (list, tuple)) or len(ids) not in {1, 2} or not all(_text(item, 160) for item in ids):
            continue
        for result_id in set(ids):
            reviews_by_result.setdefault(result_id, []).append(review)
    pairs = {}
    pair_count = 0
    comparisons = 0
    budget_exhausted = False
    pending = False
    for left in sorted(lambdas, key=lambda item: item["result_id"]):
        matching_candidates = {item["result_id"]: item for item in omegas_by_key.get(_epc_key(left), [])}
        relevant_reviews = reviews_by_result.get(left["result_id"], [])
        relevant_reviews = sorted(relevant_reviews, key=lambda item: (
            str(item.get("review_id")), str(item.get("review_revision")),
        ))
        for review in relevant_reviews:
            for result_id in review["result_ids"]:
                if result_id in omega_by_id:
                    matching_candidates[result_id] = omega_by_id[result_id]
        if not matching_candidates:
            pending = True
        for right_id in sorted(matching_candidates):
            if comparisons >= EPC_COMPARISON_BUDGET:
                budget_exhausted = True
                break
            comparisons += 1
            right = matching_candidates[right_id]
            matching_review = next((review for review in relevant_reviews if _review_matches(review, left, right)), None)
            left_key, right_key = _epc_key(left), _epc_key(right)
            automatic = left_key is not None and left_key == right_key and not _state_conflict(left, right)
            if not automatic and matching_review is None:
                pending = True
                continue
            review_id = matching_review["review_id"] if matching_review is not None else None
            revision = matching_review["review_revision"] if matching_review is not None else None
            identity = json.dumps([left["result_id"], right["result_id"], review_id, revision, PROPERTY_EVIDENCE_VERSION])
            pair_id = "legacy-epc:" + hashlib.sha256(identity.encode()).hexdigest()
            pairs[pair_id] = {
                "pair_id": pair_id, "lambda": left, "omega_log": right,
                "association_basis": "external_review" if matching_review else "explicit_state_structure_run_protocol",
                "review": {
                    key: matching_review.get(key) for key in (
                        "review_id", "review_revision", "state_id", "structure_id", "protocol_id",
                    )
                } if matching_review else None,
                "eligible_meaning": "association_complete_only",
                "allen_dynes_applicability": "not_assessed",
            }
            pair_count += 1
            if len(pairs) > EVIDENCE_LIMIT:
                del pairs[max(pairs)]
        if budget_exhausted:
            break
    ordered = [pairs[key] for key in sorted(pairs)]
    has_values = bool(candidates["lambda_eph"] or candidates["omega_log_k"])
    warnings = ["independent_property_selections_are_not_an_epc_pair", "allen_dynes_applicability_not_assessed"]
    if pending or has_values and not ordered:
        warnings.append("missing_or_conflicting_state_structure_run_protocol")
    if legacy is not None and has_values and (not lambdas or not omegas):
        warnings.append("legacy_joint_values_untraceable_or_not_selected")
    if budget_exhausted:
        warnings.append("epc_comparison_budget_exhausted_count_is_lower_bound")
    return {
        "status": "eligible" if ordered else "pending" if has_values else "not_reported",
        "selected": ordered[0] if ordered else None, "pairs": ordered[:EVIDENCE_LIMIT],
        "total_pair_count": None if budget_exhausted else pair_count,
        "total_pair_count_lower_bound": pair_count,
        "evaluated_pair_count": comparisons, "comparison_budget": EPC_COMPARISON_BUDGET,
        "total_pair_count_exact": not budget_exhausted,
        "truncated": pair_count > EVIDENCE_LIMIT or budget_exhausted,
        "warnings": warnings,
    }


def build_property_evidence(
    records: Any, *, scope_id: str, legacy_summary: Mapping[str, Any] | None = None,
    reviewed_epc_matches: Sequence[Any] = (),
    include_joint_epc: bool = True, property_fields: Sequence[str] | None = None,
    anomaly_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project bounded atomic evidence; never mutate records or perform I/O.

    reviewed_epc_matches must come from trusted, revisioned review storage, never
    from NER assertions or a client request. Default callers provide none.
    """
    from .anomaly_review import (
        ANOMALY_POLICY_VERSION,
        assess_record_anomalies,
        eligible_for_property,
    )

    context = anomaly_context or {}
    family = context.get("family", legacy_summary.get("family") if legacy_summary is not None else None)
    fields = tuple(PROPERTY_FIELDS if property_fields is None else property_fields)
    if len(set(fields)) != len(fields) or any(field not in PROPERTY_FIELDS for field in fields):
        raise ValueError("property_fields must be distinct supported property names")
    candidate_fields = tuple(dict.fromkeys((*fields, *(("lambda_eph", "omega_log_k") if include_joint_epc else ()))))
    candidates: dict[str, list[dict[str, Any]]] = {field: [] for field in candidate_fields}
    seen = set()
    for record in records if isinstance(records, (list, tuple)) else []:
        if not isinstance(record, Mapping):
            continue
        base = _base(record, scope_id)
        if base["result_id"] in seen:
            continue
        seen.add(base["result_id"])
        assessment = assess_record_anomalies(
            record, scope_id=scope_id, family=family,
            compound_thresholds=context.get("compound_thresholds", ()),
            current_year=context.get("current_year"),
        )
        # A fallback crystal/space-group selection must not smuggle an
        # ineligible lattice group back into a flat structural projection.
        if not eligible_for_property(assessment, "lattice_params"):
            base = {**base, "structure": {**base["structure"], "lattice_params": None}}
        for field in candidate_fields:
            value = _candidate(record, base, field)
            if value is not None:
                value["anomaly_review"] = assessment
                if not eligible_for_property(assessment, field):
                    value["warnings"].append("anomaly_review_required")
                candidates[field].append(value)
    return {
        "version": PROPERTY_EVIDENCE_VERSION, "not_joint_observation": True,
        "anomaly_policy_version": ANOMALY_POLICY_VERSION,
        "properties": {
            field: _property(field, candidates[field], legacy_summary, context.get("selection_policy"))
            for field in fields
        },
        "joint_epc": _joint_epc(candidates, reviewed_epc_matches, legacy_summary) if include_joint_epc else {
            "status": "not_evaluated", "selected": None, "pairs": [],
            "total_pair_count": None, "total_pair_count_lower_bound": 0,
            "total_pair_count_exact": False, "evaluated_pair_count": 0,
            "comparison_budget": EPC_COMPARISON_BUDGET, "truncated": False,
            "warnings": ["joint_epc_evaluation_not_requested"],
        },
        "warnings": ["legacy_catalogue_projection_not_an_ml_feature_row"],
    }


__all__ = [
    "ATOMIC_SELECTION_POLICY", "CATEGORICAL_PROPERTIES", "EPC_COMPARISON_BUDGET", "EVIDENCE_LIMIT", "NUMERIC_PROPERTIES",
    "PROPERTY_EVIDENCE_VERSION", "PROPERTY_FIELDS", "build_property_evidence", "legacy_result_id",
]
