"""Offline NER -> typed claim regression: no model, network or DB access."""

from copy import deepcopy
from uuid import UUID

import pytest

from ingestion.claims.mapper import map_record_to_claim
from ingestion.extract.formula_enrichment import enrich_formula
from ingestion.extract.material_ner import normalize_material_records


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
