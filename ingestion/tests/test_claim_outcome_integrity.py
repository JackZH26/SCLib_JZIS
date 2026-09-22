"""Pure mapper outcome cases; the database counterpart uses the same cases."""
from __future__ import annotations

import copy
import uuid

import pytest

from ingestion.claims.mapper import map_record_to_claim
from ingestion.claims.outcomes import negative_outcome_issues, outcome_conflicts_with_positive

SNAPSHOT = uuid.UUID("11111111-1111-4111-8111-111111111111")


def mapped(record):
    return map_record_to_claim(record, material_id="mat:synthetic-outcome", source_snapshot_id=SNAPSHOT)


@pytest.mark.parametrize("value,relation", [(12, "exact"), ("10-20 K", "interval"),
                                          (">10 K", "gt"), (">=10 K", "ge")])
def test_negative_conflicts_keep_values_but_are_not_negative_labels(value, relation):
    record = {"result_status": "not_detected", "tc_kelvin": value, "minimum_temperature_k": 2,
              "measurement_method": "resistivity", "validity_status": "accepted"}
    claim = mapped(record)
    assert claim["raw_record"] == record
    assert claim["value_relation"] == relation
    assert claim["result_status"] == "inconclusive"
    assert claim["property_type"] == "tc"
    assert claim["validity_status"] == "pending"
    assert f"negative_result_conflicts_with_{relation}_tc" in claim["extraction_metadata"]["warnings"]


@pytest.mark.parametrize("value,relation", [(None, "unreported"), ("<2 K", "lt"), ("<=2 K", "le")])
def test_explicit_negative_with_window_and_method_remains_representable(value, relation):
    claim = mapped({"result_status": "not_detected", "tc_kelvin": value,
                    "minimum_temperature_k": 2, "measurement_method": "resistivity"})
    assert claim["value_relation"] == relation
    assert not negative_outcome_issues(claim)
    assert claim["validity_status"] == "pending"  # import success is not scientific acceptance


@pytest.mark.parametrize("method", [None, "", "unknown", "not_reported"])
def test_negative_without_method_is_explicitly_blocked(method):
    claim = mapped({"result_status": "not_detected", "minimum_temperature_k": 2,
                    "measurement_method": method})
    assert "negative_result_missing_measurement_method" in claim["extraction_metadata"]["warnings"]


def test_missing_value_or_upper_bound_alone_never_infers_a_negative():
    assert mapped({})["result_status"] == "unknown"
    assert mapped({"tc_kelvin": "<2 K"})["result_status"] == "inconclusive"
    # A source can explicitly observe a transition while reporting only a bound.
    assert mapped({"result_status": "observed", "tc_kelvin": "<2 K"})["result_status"] == "observed"


@pytest.mark.parametrize("origin", [
    {"knowledge_origin": "Computed", "measurement_method": "DFT"},
    {"knowledge_origin": "Inferred", "measurement_method": "ML prediction"},
    {"knowledge_origin": "AI-Proposed", "measurement_method": "LLM hypothesis"},
    {"evidence_role": "primary_theoretical", "measurement_method": "DFT"},
])
def test_computed_or_inferred_failure_is_not_an_experimental_negative(origin):
    record = {"result_status": "not_detected", "minimum_temperature_k": 2,
              "validity_status": "accepted", **origin}
    claim = mapped(record)
    assert claim["result_status"] == "inconclusive"
    assert claim["property_type"] == "tc"
    assert claim["validity_status"] == "pending"
    assert claim["raw_record"] == record
    assert "negative_result_requires_experimental_evidence" in claim["extraction_metadata"]["warnings"]


@pytest.mark.parametrize("field", ["result_status", "outcome_state", "outcome"])
@pytest.mark.parametrize("value", [
    "not_detected", "not_observed", "notdetected", "no_transition", "no_superconductivity",
    "non_superconducting", "negative", "inconclusive", "ambiguous", "uncertain", "unknown",
    "unreported",
])
def test_every_nonpositive_alias_vetoes_a_positive_interpretation(field, value):
    assert outcome_conflicts_with_positive({field: value})


@pytest.mark.parametrize("marker", [
    {"outcome": "negative"}, {"outcome_state": "unknown"}, {"no_transition": True},
    {"not_detected": True}, {"superconductivity_observed": False},
    {"transition_observed": False}, {"is_superconducting": False},
])
def test_positive_alias_never_masks_later_conflicting_marker_in_mapper(marker):
    record = {"result_status": "observed", "tc_kelvin": 12, **marker}
    claim = mapped(record)
    assert claim["raw_record"] == record
    assert claim["result_status"] == "inconclusive"
    assert claim["value_kelvin"] == 12
    assert claim["validity_status"] == "pending"
    assert "positive_result_conflicts_with_outcome_markers" in claim["extraction_metadata"]["warnings"]


def test_only_reserved_derived_annotations_are_excluded_from_source_identity():
    original = {"tc_kelvin": 12.0, "measurement": "resistivity", "pressure_gpa": None}
    annotated = {**original, "result_classification": {"arbitrary_derived": "v2"},
                 "pressure_semantics": {"arbitrary_derived": "v2"},
                 "property_evidence": {"arbitrary_derived": "v1"},
                 "anomaly_review": {"arbitrary_derived": "v1"}}
    first, second = mapped(original), mapped(annotated)
    assert (first["id"], first["source_record_hash"]) == (second["id"], second["source_record_hash"])
    changed = copy.deepcopy(original)
    changed["tc_kelvin"] = 13.0
    assert mapped(changed)["source_record_hash"] != first["source_record_hash"]
    assert second["raw_record"] == annotated
