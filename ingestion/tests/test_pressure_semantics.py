"""Shared pressure contract and ingestion integration, without DB/cloud calls."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from ingestion.claims.mapper import map_record_to_claim
from ingestion.extract.fact_sentences import fact_sentence
from ingestion.extract.hydride_ner import clean_hydride_record
from ingestion.extract.material_ner import normalize_material_records
from ingestion.extract.materials_aggregator import _derive_summary
from ingestion.extract.scientific_values import parse_scientific_value
from ingestion.pressure_semantics import (
    PRESSURE_POLICY_VERSION,
    annotate_pressure_records,
    classify_pressure,
    pressure_matches,
)


@pytest.mark.parametrize(
    ("record", "state", "value"),
    [
        ({}, "not_reported", None),
        ({"pressure_gpa": None, "ambient_sc": True, "sample_form": "bulk"}, "not_reported", None),
        ({"pressure_gpa": 0}, "ambiguous", 0),
        ({"pressure_gpa": 0, "ambient_sc": True, "pressure_type": "none"}, "ambiguous", 0),
        ({"pressure_gpa": 0, "pressure_state": "explicit_ambient"}, "explicit_ambient", 0),
        ({"pressure_state": "explicit_ambient"}, "ambiguous", None),
        ({"pressure_gpa": "ambient pressure"}, "explicit_ambient", 0),
        ({"pressure_condition": "at atmospheric pressure"}, "explicit_ambient", 0),
        (
            {"pressure_condition_normalized": "ambient", "tc_regime": "bulk_equilibrium"},
            "not_reported",
            None,
        ),
        ({"pressure_gpa": "20 kbar"}, "reported", 2),
        ({"pressure_gpa": "1e-3 GPa"}, "reported", 0.001),
        ({"pressure_gpa": 200, "pressure_condition": "ambient"}, "ambiguous", 200),
        ({"pressure_gpa": -1}, "ambiguous", -1),
        ({"pressure_gpa": True}, "ambiguous", None),
        ({"pressure_gpa": "20 K"}, "ambiguous", None),
        ({"pressure_gpa": "1e999 GPa"}, "ambiguous", None),
        ({"pressure_gpa": float("nan")}, "ambiguous", None),
    ],
)
def test_pressure_evidence_is_explicit_and_finite(record, state, value):
    assessment = classify_pressure(record)
    assert assessment.pressure_state == state
    assert assessment.pressure_gpa == value
    assert assessment.classifier_version == PRESSURE_POLICY_VERSION
    json.dumps(assessment.to_dict(), allow_nan=False)


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"pressure_gpa": 0},
        {"pressure_gpa": -1},
        {"pressure_gpa": True},
    ],
)
def test_no_pressure_predicate_never_filters_by_pressure(record):
    assert pressure_matches(classify_pressure(record))


def test_unknown_opt_in_never_mislabels_negative_pressure_as_ambient():
    unknown = classify_pressure({})
    assert not pressure_matches(unknown, ambient_only=True)
    assert pressure_matches(unknown, ambient_only=True, include_unknown=True)
    assert not pressure_matches(
        classify_pressure({"pressure_gpa": -1}), ambient_only=True, include_unknown=True
    )


def test_range_filters_require_entire_reported_extent():
    assessment = classify_pressure({"pressure_gpa": "20–30 kbar"})
    assert assessment.pressure_state == "reported"
    assert assessment.pressure_gpa is None
    assert (assessment.value_lower_gpa, assessment.value_upper_gpa) == (2, 3)
    assert pressure_matches(assessment, min_gpa=2, max_gpa=3)
    assert not pressure_matches(assessment, max_gpa=2.5)
    assert not pressure_matches(assessment, min_gpa=2.5)
    assert not pressure_matches(assessment, ambient_only=True)
    one_sided = classify_pressure({"pressure_gpa": "<2 GPa"})
    assert pressure_matches(one_sided, max_gpa=2)
    assert not pressure_matches(one_sided, min_gpa=0)


def test_uncertainty_and_approximation_are_not_silently_exact():
    assessment = classify_pressure({"pressure_gpa": "20±2 kbar"})
    assert assessment.uncertainty_gpa == 0.2
    assert assessment.uncertainty_interpretation == "unspecified"
    assert pressure_matches(assessment, min_gpa=1.8, max_gpa=2.2)
    assert not pressure_matches(assessment, max_gpa=2.1)
    assert not pressure_matches(classify_pressure({"pressure_gpa": "~2 GPa"}), max_gpa=3)


@pytest.mark.parametrize(
    "bounds", [{"min_gpa": 3, "max_gpa": 2}, {"max_gpa": True}, {"min_gpa": float("inf")}]
)
def test_invalid_filter_bounds_fail_closed(bounds):
    with pytest.raises(ValueError):
        pressure_matches(classify_pressure({}), **bounds)


def test_envelope_and_scalar_tampering_do_not_replace_raw_quantity():
    raw = parse_scientific_value("20 kbar", "pressure_gpa", source_locator={"table": "1"})
    record = {
        "pressure_gpa": 999,
        "scientific_values": {"pressure_gpa": {**raw, "value": 999}},
        "pressure_semantics": {"pressure_state": "explicit_ambient", "pressure_gpa": 0},
    }
    assert classify_pressure(record).pressure_gpa == 2
    before = deepcopy(record)
    annotated = annotate_pressure_records([record])
    assert record == before
    assert annotated[0] is not record
    assert annotated[0]["pressure_semantics"]["raw_value"] == "20 kbar"


def test_numeric_parser_and_pressure_policy_agree_on_supported_quantities():
    for raw in (
        "20 kbar",
        "1e-3 GPa",
        "2000 MPa",
        "2±0.2 GPa",
        "2–3 GPa",
        "<2 GPa",
        ["20 kbar", "3 GPa"],
    ):
        value = parse_scientific_value(raw, "pressure_gpa")
        pressure = classify_pressure({"pressure_gpa": raw})
        assert (
            pressure.relation,
            pressure.pressure_gpa,
            pressure.value_lower_gpa,
            pressure.value_upper_gpa,
            pressure.uncertainty_gpa,
        ) == (
            value["relation"],
            value["value"],
            value["lower"],
            value["upper"],
            value["uncertainty"],
        )


def test_v1_claim_preserves_range_without_manufactured_scalar():
    record = {"formula": "H3S", "tc_kelvin": 200, "pressure_gpa": "150–160 GPa"}
    claim = map_record_to_claim(
        record,
        material_id="mat:h3s",
        source_snapshot_id=UUID("11111111-1111-4111-8111-111111111111"),
    )
    assert claim["pressure_state"] == "ambiguous"
    assert claim["pressure_gpa"] is None
    metadata = claim["extraction_metadata"]["pressure_semantics"]
    assert metadata["pressure_state"] == "reported"
    assert (metadata["value_lower_gpa"], metadata["value_upper_gpa"]) == (150, 160)
    assert claim["raw_record"] == record


def test_ner_ambient_condition_survives_to_shared_classifier():
    raw = {
        "formula": "MgB2",
        "tc_kelvin": "39 K",
        "pressure_gpa": 0,
        "pressure_condition": "ambient pressure",
        "evidence_type": "primary_experimental",
    }
    record = normalize_material_records([raw], paper_type="experimental")[0]
    assert record["pressure_semantics"]["pressure_state"] == "explicit_ambient"
    assert record["raw_extraction"] == raw


def test_hydride_provenance_is_preferred_over_compatibility_scalars():
    record = clean_hydride_record(
        {"formula": "H3S", "tc_kelvin": 200, "pressure_gpa": "150–160 GPa", "lambda_eph": 2}
    )
    assert record["pressure_gpa"] is None
    assessment = classify_pressure(record)
    assert assessment.pressure_state == "reported"
    assert assessment.value_upper_gpa == 160


def test_fact_sentences_never_infer_ambient_from_bulk_or_legacy_zero():
    for extra in (
        {"tc_regime": "bulk_equilibrium"},
        {"ambient_sc": True},
        {"pressure_gpa": 0},
        {"pressure_gpa": -1},
    ):
        assert "ambient pressure" not in fact_sentence(
            {"formula": "MgB2", "tc_kelvin": 39, **extra}
        )
    assert "at 2 GPa" in fact_sentence(
        {"formula": "H3S", "tc_kelvin": 20, "pressure_gpa": "20 kbar"}
    )
    assert "[2, 3] GPa" in fact_sentence(
        {"formula": "H3S", "tc_kelvin": 20, "pressure_gpa": "20–30 kbar"}
    )


def test_material_ambient_summary_requires_same_result_pressure_evidence():
    raw = {
        "formula": "MgB2",
        "paper_id": "synthetic:1",
        "tc_kelvin": 39,
        "evidence_type": "primary_experimental",
        "ambient_sc": True,
        "pressure_gpa": 0,
    }
    unknown = _derive_summary("MgB2", [raw])
    assert unknown["tc_ambient"] is None
    assert unknown["ambient_sc"] is None
    assert "ambient" not in unknown["tc_max_conditions"]
    explicit = _derive_summary("MgB2", [{**raw, "pressure_condition": "ambient pressure"}])
    assert explicit["tc_ambient"] == 39
    assert explicit["ambient_sc"] is True


def test_api_and_ingestion_pressure_modules_are_byte_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "ingestion/ingestion/pressure_semantics.py").read_bytes() == (
        root / "api/services/pressure_semantics.py"
    ).read_bytes()


@pytest.mark.parametrize("proposal", [
    {"status": "parsed", "relation": "interval", "lower": 1, "upper": 3, "unit": "GPa"},
    {"status": "invalid", "errors": ["unit_mismatch"], "source_locator": {"page": 2}},
    {}, None, 2, "2 GPa",
])
def test_typed_pressure_without_raw_never_falls_back_to_cached_scalar(proposal):
    record = {
        "pressure_gpa": 0,
        "pressure_condition": "ambient pressure",
        "scientific_values": {"pressure_gpa": proposal},
    }
    original = deepcopy(record)
    assessment = classify_pressure(record)
    assert assessment.pressure_state == "ambiguous"
    assert assessment.pressure_gpa is None
    assert assessment.value_lower_gpa is None
    assert assessment.value_upper_gpa is None
    assert assessment.raw_value == proposal
    assert "missing_raw_proposal" in assessment.reasons
    assert not pressure_matches(assessment, max_gpa=2)
    assert not pressure_matches(assessment, ambient_only=True)
    assert record == original
