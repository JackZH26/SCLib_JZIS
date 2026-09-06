"""Raw scientific proposals, unit conversion and lossless typed relations."""

import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

from ingestion.extract.scientific_values import (
    PARSER_VERSION,
    legacy_scalar,
    parse_scientific_value,
    record_quantity,
)


@pytest.mark.parametrize(
    ("raw", "field", "value", "unit"),
    [
        ("1e-3 K", "tc_kelvin", 0.001, "K"),
        ("20 kbar", "pressure_gpa", 2, "GPa"),
        ("2000 MPa", "pressure_gpa", 2, "GPa"),
        ("30 mK", "tc_kelvin", 0.03, "K"),
        ("500 mT", "hc2_tesla", 0.5, "T"),
        ("0.4 nm", "lattice_a", 4, "angstrom"),
        ("0.002 eV", "rho_s_mev", 2, "meV"),
        ("16%", "doping_level", 0.16, "1"),
        ("0.4 nm", "lattice_b", 4, "angstrom"),
        ("90 deg", "lattice_alpha", 90, "degree"),
        ("0.2 K", "measurement_temperature_k", 0.2, "K"),
        ("10 mK", "hc2_temperature_k", 0.01, "K"),
        ("100 Å", "lambda_london_nm", 10, "nm"),
        ("500 pm", "xi_gl_nm", 0.5, "nm"),
        ("20 angstrom", "layer_thickness_nm", 2, "nm"),
    ],
)
def test_property_aware_unit_conversion_preserves_source(raw, field, value, unit):
    result = parse_scientific_value(
        raw, field, source_context="synthetic fixture", source_locator={"table": "1"}
    )
    assert result["status"] == "parsed"
    assert result["value"] == pytest.approx(value)
    assert result["unit"] == unit
    assert result["raw_value"] == raw
    assert result["unit_basis"] == "explicit"
    assert result["source_locator"] == {"table": "1"}
    assert result["parser_version"] == PARSER_VERSION


@pytest.mark.parametrize(
    ("raw", "relation", "lower", "upper"),
    [
        ("<2 K", "lt", None, 2),
        ("≤2 K", "le", None, 2),
        (">3 K", "gt", 3, None),
        (">=3 K", "ge", 3, None),
        ("80–95 K", "interval", 80, 95),
        ("1e-3-2e-3 K", "interval", 0.001, 0.002),
        (["10 mK", "0.02 K"], "interval", 0.01, 0.02),
    ],
)
def test_bounds_and_intervals_never_become_point_values(raw, relation, lower, upper):
    result = parse_scientific_value(raw, "tc_kelvin")
    assert result["relation"] == relation
    assert result["value"] is None
    assert result["lower"] == lower
    assert result["upper"] == upper
    assert legacy_scalar(result) is None


def test_uncertainty_keeps_unspecified_statistical_interpretation():
    result = parse_scientific_value("0.16±0.02", "lambda_eph")
    assert result["value_kind"] == "point_with_uncertainty"
    assert result["value"] == 0.16
    assert result["uncertainty"] == 0.02
    assert result["uncertainty_interpretation"] == "unspecified"
    converted = parse_scientific_value("20 +/- 2 kbar", "pressure_gpa")
    assert converted["value"] == 2
    assert converted["uncertainty"] == 0.2


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        (True, "tc_kelvin"),
        (math.nan, "tc_kelvin"),
        (math.inf, "tc_kelvin"),
        ("1e999 K", "tc_kelvin"),
        ("20 kbar", "tc_kelvin"),
        ("5 THz", "omega_log_k"),
        ("5 Oe", "hc2_tesla"),
        ("1.0±-0.2", "lambda_eph"),
        ("95–80 K", "tc_kelvin"),
        ("0.16(2)", "doping_level"),
        ({"value": 2}, "tc_kelvin"),
    ],
)
def test_invalid_or_unsupported_input_stays_archived_without_scalar(raw, field):
    result = parse_scientific_value(raw, field)
    assert result["status"] == "invalid"
    assert result["errors"]
    assert legacy_scalar(result) is None
    json.dumps(result, allow_nan=False)


def test_explicit_unit_conflict_is_not_resolved_by_guessing():
    result = parse_scientific_value("20 kbar", "pressure_gpa", raw_unit="GPa")
    assert result["errors"] == ["conflicting_units"]


def test_preserved_proposal_is_reparsed_and_normalized_tampering_ignored():
    original = parse_scientific_value("20 kbar", "pressure_gpa", source_locator={"page": 2})
    record = {
        "pressure_gpa": 999,
        "scientific_values": {"pressure_gpa": {**original, "value": 999}},
    }
    result = record_quantity(record, "pressure_gpa")
    assert result == original


def test_missing_and_bare_units_are_explicit_not_source_validated():
    assert parse_scientific_value(None, "tc_kelvin")["status"] == "unreported"
    assert parse_scientific_value(20, "pressure_gpa")["unit_basis"] == "field_schema_assumption"


def test_approximation_is_not_erased():
    result = parse_scientific_value("approximately 39 K", "tc_kelvin")
    assert result["approximate"] is True
    assert result["raw_value"] == "approximately 39 K"


@pytest.mark.parametrize("proposal", [
    {"status": "parsed", "relation": "interval", "lower": 80, "upper": 95, "unit": "K"},
    {"status": "invalid", "errors": ["unit_mismatch"], "source_locator": {"table": 1}},
    {}, None, 300, "300 K",
])
def test_typed_proposal_without_raw_is_archived_not_replaced_by_cached_scalar(proposal):
    record = {"tc_kelvin": 300, "scientific_values": {"tc_kelvin": proposal}}
    original = deepcopy(record)
    value = record_quantity(record, "tc_kelvin")
    assert value["status"] == "invalid"
    assert value["errors"] == ["missing_raw_proposal"]
    assert value["relation"] == "unreported"
    assert value["value"] is None and value["lower"] is None and value["upper"] is None
    assert value["raw_value"] == proposal
    assert legacy_scalar(value) is None
    assert record == original
    json.dumps(value, allow_nan=False)


def test_api_and_ingestion_scientific_parsers_are_byte_identical():
    root = Path(__file__).resolve().parents[2]
    assert (root / "ingestion/ingestion/extract/scientific_values.py").read_bytes() == (
        root / "api/services/scientific_values.py"
    ).read_bytes()


@pytest.mark.parametrize("raw", [["~80 K", "95 K"], ["80 K", "approximately 95 K"]])
def test_approximate_sequence_endpoints_cannot_prove_exact_interval(raw):
    value = parse_scientific_value(raw, "tc_kelvin")
    assert value["status"] == "invalid"
    assert value["errors"] == ["invalid_interval_endpoints"]
    assert value["raw_value"] == raw
    assert value["lower"] is None and value["upper"] is None
    assert legacy_scalar(value) is None
