"""Unit tests for the hydride-specific parameter NER post-processor."""
from __future__ import annotations

import pytest

from ingestion.extract.hydride_ner import clean_hydride_record


def test_clean_hydride_record_converts_omega_mev() -> None:
    rec = clean_hydride_record({
        "formula": "LaH10",
        "tc_kelvin": "250 K",
        "pressure_gpa": "170 GPa",
        "lambda_eph": "2.35",
        "mu_star": "0.10",
        "omega_log_source_value": "100",
        "omega_log_source_unit": "meV",
        "method": "Eliashberg",
        "evidence_type": "primary_theoretical",
        "confidence": 0.9,
    }, model="gemini-test")

    assert rec is not None
    assert rec["formula"] == "LaH10"
    assert rec["formula_normalized"] == "LaH10"
    assert rec["tc_kelvin"] == 250
    assert rec["pressure_gpa"] == 170
    assert rec["lambda_eph"] == 2.35
    assert rec["mu_star"] == 0.10
    assert rec["omega_log_k"] == pytest.approx(1160.45)
    assert rec["omega_log_source_unit"] == "meV"
    assert rec["model"] == "gemini-test"


def test_clean_hydride_record_rejects_non_hydride() -> None:
    assert clean_hydride_record({
        "formula": "MgB2",
        "tc_kelvin": 39,
        "lambda_eph": 0.7,
    }) is None


def test_clean_hydride_record_rejects_obvious_range_errors() -> None:
    assert clean_hydride_record({
        "formula": "H3S",
        "tc_kelvin": 200,
        "pressure_gpa": 900,
    }) is None


def test_clean_hydride_record_flags_allen_dynes_mismatch() -> None:
    rec = clean_hydride_record({
        "formula": "H3S",
        "tc_kelvin": 200,
        "pressure_gpa": 155,
        "lambda_eph": 2.0,
        "mu_star": 0.1,
        "omega_log_k": 100,
    })

    assert rec is not None
    assert "allen_dynes_mismatch" in rec["validation_flags"]
    assert rec["provenance"]["allen_dynes_tc_k"] < 20


def test_clean_hydride_record_accepts_c_s_h_shorthand() -> None:
    rec = clean_hydride_record({
        "formula": "C-S-H",
        "tc_kelvin": 287,
        "pressure_gpa": 267,
    })

    assert rec is not None
    assert rec["formula"] == "CSH"
