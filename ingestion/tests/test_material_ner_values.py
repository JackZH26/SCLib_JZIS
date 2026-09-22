"""Offline NER -> typed claim regression: no model, network or DB access."""

from copy import deepcopy
from uuid import UUID

import pytest

from ingestion.claims.mapper import map_record_to_claim
from ingestion.claims.outcomes import negative_outcome_issues, outcome_conflicts_with_positive
from ingestion.extract.formula_enrichment import enrich_formula
from ingestion.extract.material_ner import (
    NER_EXTRACTOR_VERSION,
    _build_prompt,
    normalize_material_records,
)
from ingestion.extract.scientific_values import record_quantity
from ingestion.result_semantics import classify_result


def _normalized(raw):
    return normalize_material_records(
        [raw], paper_type="experimental", paper_id="synthetic:fixture"
    )[0]


def _claim(record):
    return map_record_to_claim(
        record,
        material_id="mat:synthetic",
        source_snapshot_id=UUID("11111111-1111-4111-8111-111111111111"),
    )


@pytest.mark.parametrize(
    ("tc", "relation", "value", "lower", "upper"),
    [
        ("1e-3 K", "exact", 0.001, None, None),
        ("<2 K", "lt", None, None, 2),
        ("80–95 K", "interval", None, 80, 95),
    ],
)
def test_ner_to_claim_does_not_lose_scientific_semantics(tc, relation, value, lower, upper):
    raw = {
        "formula": "MgB₂",
        "tc_kelvin": tc,
        "pressure_gpa": "20 kbar",
        "evidence_type": "primary_experimental",
        "evidence_text": "Synthetic source quotation.",
        "source_locator": {"page": 3, "table": "2"},
    }
    before = deepcopy(raw)
    normalized = _normalized(raw)
    assert raw == before
    assert normalized["raw_extraction"] == raw
    assert normalized["pressure_gpa"] == 2
    if relation != "exact":
        assert "tc_kelvin" not in normalized
    claim = _claim(normalized)
    assert claim["value_relation"] == relation
    assert claim["value_kelvin"] == value
    assert claim["value_lower_kelvin"] == lower
    assert claim["value_upper_kelvin"] == upper
    assert claim["pressure_gpa"] == 2
    assert claim["source_locator"]["page"] == 3
    proposal = claim["extraction_metadata"]["scientific_values"]["tc_kelvin"]
    assert proposal["raw_value"] == tc
    assert proposal["source_context"] == raw["evidence_text"]
    assert claim["validity_status"] == "pending"


def test_uncertainty_survives_in_claim_metadata_and_semantic_identity():
    first = _claim(
        _normalized({"formula": "MgB2", "tc_kelvin": "39±1 K", "lambda_eph": "0.16±0.02"})
    )
    second = _claim(_normalized({"formula": "MgB2", "tc_kelvin": "39±2 K"}))
    assert first["extraction_metadata"]["scientific_values"]["tc_kelvin"]["uncertainty"] == 1
    assert first["extraction_metadata"]["scientific_values"]["lambda_eph"]["uncertainty"] == 0.02
    assert first["semantic_fingerprint"] != second["semantic_fingerprint"]


@pytest.mark.parametrize("raw", ["NaN", True, "39 GPa"])
def test_invalid_ner_values_remain_reviewable_and_cannot_be_accepted(raw):
    normalized = _normalized({"formula": "MgB2", "tc_kelvin": raw})
    assert "tc_kelvin" not in normalized
    assert normalized["scientific_values"]["tc_kelvin"]["status"] == "invalid"
    assert normalized["validation_flags"]
    claim = _claim(normalized)
    assert claim["value_relation"] == "unreported"
    assert claim["validity_status"] == "pending"


def test_isotope_notation_survives_even_if_model_already_flattened_display_formula():
    record = _normalized({"formula": "La2Cu18O4", "formula_raw": "La₂Cu¹⁸O₄", "tc_kelvin": "30 K"})
    assert record["formula_raw"] == "La₂Cu¹⁸O₄"
    assert "¹⁸" in record["formula"]
    assert enrich_formula(record["formula"])["composition_status"] != "exact"
    assert record["composition_proposal"]["atomic_fractions"] is None
    assert _claim(record)["raw_record"]["formula_raw"] == "La₂Cu¹⁸O₄"


def test_result_classification_is_derived_without_mutating_raw_occurrence():
    raw = {"formula": "MgB2", "tc_kelvin": "39 K", "evidence_type": "primary_theoretical"}
    record = _normalized(raw)
    assert "result_classification" not in record
    assert _claim(record)["extraction_metadata"]["result_classification"]["knowledge_origin"] == "Computed"
    assert record["raw_extraction"] == raw


@pytest.mark.parametrize("tc", [0.001, 400.0])
def test_numeric_anomaly_does_not_rewrite_extraction_confidence_or_source_value(tc):
    raw = {"formula": "MgB2", "tc_kelvin": tc, "confidence": 0.95,
           "pressure_gpa": 150.0, "measurement": "resistivity"}
    record = _normalized(raw)
    assert record["tc_kelvin"] == tc
    assert record["confidence"] == 0.95
    assert record["raw_extraction"] == raw


@pytest.mark.parametrize("tc", [None, "<300 mK", "≤300 mK"])
def test_explicit_negative_retains_detection_window_units_and_pending_status(tc):
    raw = {
        "formula": "MgB2", "tc_kelvin": tc, "result_status": "not_detected",
        "knowledge_origin": "Observed", "source_role": "primary",
        "measurement_method": "resistivity", "minimum_temperature_k": "300 mK",
        "magnetic_field_t": "10 mT", "pressure_gpa": "20 kbar",
        "detection_conditions": {"temperature_min_k": 0.3, "magnetic_field_t": 0.01},
        "evidence_text": "Synthetic sample-specific non-detection.",
        "source_locator": {"table": "2", "row": "sample A"},
        "validity_status": "accepted",
    }
    before = deepcopy(raw)
    record = _normalized(raw)
    assert record["result_status"] == "not_detected"
    assert record["minimum_temperature_k"] == 0.3
    assert record["magnetic_field_t"] == 0.01
    assert record["pressure_gpa"] == 2
    assert record["detection_conditions"] == raw["detection_conditions"]
    assert "validity_status" not in record
    assert raw == before and record["raw_extraction"] == before
    claim = _claim(record)
    assert claim["result_status"] == "not_detected"
    assert claim["property_type"] == "non_transition"
    assert claim["minimum_temperature_k"] == 0.3
    assert claim["magnetic_field_t"] == 0.01
    assert not negative_outcome_issues(claim)
    assert claim["validity_status"] == "pending"


@pytest.mark.parametrize("field,raw_value,relation", [
    ("minimum_temperature_k", "200–300 mK", "interval"),
    ("minimum_temperature_k", "<300 mK", "lt"),
    ("magnetic_field_t", ">10 mT", "gt"),
])
def test_detection_bounds_and_intervals_are_not_fabricated_scalar_limits(field, raw_value, relation):
    raw = {"formula": "MgB2", "result_status": "not_detected",
           "measurement_method": "resistivity", field: raw_value}
    record = _normalized(raw)
    assert field not in record
    assert record["scientific_values"][field]["relation"] == relation
    assert record["scientific_values"][field]["raw_value"] == raw_value
    assert record_quantity(record, field)["relation"] == relation
    assert record["raw_extraction"] == raw
    assert _claim(record)["validity_status"] == "pending"


def test_detection_uncertainty_remains_in_reparseable_quantity_proposal():
    record = _normalized({"formula": "MgB2", "minimum_temperature_k": "300 ± 20 mK",
                          "magnetic_field_t": "10 ± 1 mT"})
    for field, value, uncertainty in (("minimum_temperature_k", 0.3, 0.02),
                                      ("magnetic_field_t", 0.01, 0.001)):
        proposal = record_quantity(record, field)
        assert proposal["value"] == value
        assert proposal["uncertainty"] == uncertainty
        assert proposal["uncertainty_interpretation"] == "unspecified"


@pytest.mark.parametrize("field", ["minimum_temperature_k", "magnetic_field_t"])
@pytest.mark.parametrize("value", [True, False, "NaN", "infinity", {"value": 1}, "3 angstrom"])
def test_malformed_detection_quantities_never_coerce_to_numeric_labels(field, value):
    raw = {"formula": "MgB2", "result_status": "not_detected", field: value}
    record = _normalized(raw)
    assert field not in record
    assert record["scientific_values"][field]["status"] == "invalid"
    assert record["raw_extraction"] == raw
    assert any(flag.startswith(field + ":") for flag in record["validation_flags"])
    assert _claim(record)[field] is None


@pytest.mark.parametrize("marker", [
    {"outcome_state": "no_transition"}, {"outcome": "negative"},
    {"no_transition": True}, {"not_detected": True},
    {"superconductivity_observed": False}, {"transition_observed": False},
    {"is_superconducting": False},
])
def test_all_outcome_aliases_survive_and_conflicting_positive_is_not_promoted(marker):
    raw = {"formula": "MgB2", "result_status": "observed", "tc_kelvin": 12, **marker}
    record = _normalized(raw)
    assert {field: record[field] for field in marker} == marker
    assert outcome_conflicts_with_positive(record)
    claim = _claim(record)
    assert claim["result_status"] == "inconclusive"
    assert claim["value_kelvin"] == 12
    assert claim["validity_status"] == "pending"
    assert record["raw_extraction"] == raw


@pytest.mark.parametrize("signals,origin,status,role", [
    ({"knowledge_origin": "Computed", "source_role": "cited"}, "Computed", "resolved", "cited"),
    ({"result_origin": "Inferred", "source_role": "primary"}, "Inferred", "resolved", "primary"),
    ({"claim_kind": "AI-Proposed", "source_role": "primary"}, "AI-Proposed", "resolved", "primary"),
    ({"method": "DFT", "source_role": "cited"}, "Computed", "resolved", "cited"),
    ({"knowledge_origin": "Observed", "result_origin": "Computed"}, "Unknown", "conflicted", "unknown"),
    ({"knowledge_origin": "Computed", "measurement_method": "resistivity"}, "Unknown", "conflicted", "unknown"),
    ({"evidence_role": "primary_theoretical", "measurement": "resistivity"}, "Unknown", "conflicted", "primary"),
    ({"evidence_type": "primary_experimental", "source_role": "cited"}, "Observed", "resolved", "conflicted"),
    # These are valid shared-classifier legacy aliases, not the prompt's
    # preferred spellings. Dropping them would hide an actual conflict.
    ({"evidence_type": "experimental", "knowledge_origin": "Computed"}, "Unknown", "conflicted", "unknown"),
    ({"evidence_type": "cited_prior_work", "source_role": "primary"}, "Unknown", "unknown", "conflicted"),
])
def test_independent_origin_and_source_role_signals_are_never_reconciled_away(signals, origin, status, role):
    raw = {"formula": "MgB2", "tc_kelvin": 12, **signals}
    record = _normalized(raw)
    assert {field: record[field] for field in signals} == signals
    result = classify_result(record)
    assert (result.knowledge_origin, result.classification_status, result.source_role) == (origin, status, role)
    assert "result_classification" not in record
    assert record["raw_extraction"] == raw
    assert _claim(record)["validity_status"] == "pending"


@pytest.mark.parametrize("paper_type", ["experimental", "computational", "theoretical"])
def test_genre_and_missing_detection_conditions_do_not_supply_result_or_negative_evidence(paper_type):
    raw = {"formula": "MgB2", "tc_kelvin": "<2 K",
           "detection_conditions": {"temperature_min_k": 2}, "confidence": 0.99}
    record = normalize_material_records([raw], paper_type=paper_type)[0]
    assert not {"knowledge_origin", "source_role", "result_status", "minimum_temperature_k"} & record.keys()
    assert classify_result(record).knowledge_origin == "Unknown"
    assert _claim(record)["result_status"] == "inconclusive"


@pytest.mark.parametrize("field", ["result_status", "outcome_state", "outcome", "knowledge_origin",
                                   "result_origin", "evidence_role", "evidence_type", "source_role",
                                   "claim_kind", "measurement", "measurement_method", "method"])
@pytest.mark.parametrize("value", [True, 1, ["Observed"], {"label": "observed"}])
def test_result_text_fields_require_strings_without_manufacturing_assertions(field, value):
    raw = {"formula": "MgB2", field: value}
    record = _normalized(raw)
    assert field not in record
    assert f"{field}:explicit_text_required" in record["validation_flags"]
    assert record["raw_extraction"] == raw
    assert classify_result(record).knowledge_origin == "Unknown"
    assert _claim(record)["result_status"] == "unknown"


@pytest.mark.parametrize("field", ["no_transition", "not_detected", "superconductivity_observed",
                                   "transition_observed", "is_superconducting"])
@pytest.mark.parametrize("value", [1, 0, "true", "false", [], {}])
def test_outcome_flags_require_json_booleans(field, value):
    raw = {"formula": "MgB2", field: value}
    record = _normalized(raw)
    assert field not in record
    assert f"{field}:explicit_boolean_required" in record["validation_flags"]
    assert record["raw_extraction"] == raw
    assert not outcome_conflicts_with_positive(record)
    assert _claim(record)["result_status"] == "unknown"


def test_prompt_requests_explicit_negative_window_and_independent_result_origin():
    prompt = _build_prompt("Synthetic source only.", "computational")
    assert "minimum_temperature_k" in prompt and "magnetic_field_t" in prompt
    assert '"not_detected" ONLY for an explicit statement' in prompt
    assert 'source_role: "primary" | "cited" | "unknown"' in prompt
    assert "Paper genre, family" in prompt
    assert 'if confidence < 0.5, set evidence_type = "cited"' not in prompt
    assert "confidence <= 0.5" not in prompt


def test_fresh_normalizer_records_actual_extractor_version_without_trusting_input_marker():
    raw = {"formula": "MgB2", "tc_kelvin": "39 K", "extractor_version": "forged-input-version"}
    before = deepcopy(raw)
    record = _normalized(raw)
    assert record["extractor_version"] == NER_EXTRACTOR_VERSION
    assert record["raw_extraction"] == before and raw == before
