"""Unit tests for the hydride-specific parameter NER post-processor."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ingestion.extract import hydride_ner
from ingestion.extract.hydride_ner import HydrideNerError, clean_hydride_record
from ingestion.models import PaperMetadata, ParsedPaper


@pytest.fixture(autouse=True)
def isolated_hydride_settings(monkeypatch):
    """These unit tests neither need nor read service credentials/DSNs."""
    monkeypatch.setattr(
        "ingestion.config.get_settings", lambda: SimpleNamespace(gemini_model="synthetic-model")
    )


def test_clean_hydride_record_converts_omega_mev() -> None:
    rec = clean_hydride_record(
        {
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
        },
        model="gemini-test",
    )

    assert rec is not None
    assert rec["formula"] == "LaH10"
    # Normalized formulas are lowercase grouping keys; ``formula`` above is
    # the case-preserving display value.
    assert rec["formula_normalized"] == "lah10"
    assert rec["tc_kelvin"] == 250
    assert rec["pressure_gpa"] == 170
    assert rec["lambda_eph"] == 2.35
    assert rec["mu_star"] == 0.10
    assert rec["omega_log_k"] == pytest.approx(1160.45)
    assert rec["omega_log_source_unit"] == "meV"
    assert rec["model"] == "gemini-test"


def test_clean_hydride_record_rejects_non_hydride() -> None:
    assert (
        clean_hydride_record(
            {
                "formula": "MgB2",
                "tc_kelvin": 39,
                "lambda_eph": 0.7,
            }
        )
        is None
    )


def test_clean_hydride_record_rejects_obvious_range_errors() -> None:
    assert (
        clean_hydride_record(
            {
                "formula": "H3S",
                "tc_kelvin": 200,
                "pressure_gpa": 900,
            }
        )
        is None
    )


def test_clean_hydride_record_flags_allen_dynes_mismatch() -> None:
    rec = clean_hydride_record(
        {
            "formula": "H3S",
            "tc_kelvin": 200,
            "pressure_gpa": 155,
            "lambda_eph": 2.0,
            "mu_star": 0.1,
            "omega_log_k": 100,
        }
    )

    assert rec is not None
    assert "allen_dynes_mismatch" in rec["validation_flags"]
    assert rec["provenance"]["allen_dynes_tc_k"] < 20


def test_clean_hydride_record_accepts_c_s_h_shorthand() -> None:
    rec = clean_hydride_record(
        {
            "formula": "C-S-H",
            "tc_kelvin": 287,
            "pressure_gpa": 267,
        }
    )

    assert rec is not None
    assert rec["formula"] == "CSH"


def test_extract_hydride_parameters_raises_on_model_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_generate(_model: str, _prompt: str) -> object:
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(hydride_ner, "_generate_content_with_retry", broken_generate)

    parsed = ParsedPaper(
        meta=PaperMetadata(
            arxiv_id="2601.00001",
            title="Hydride test",
            authors=[],
            abstract="LaH10 has Tc near 250 K at high pressure.",
            date_submitted=None,
            categories=[],
            primary_category=None,
        ),
        sections=[],
    )

    with pytest.raises(HydrideNerError):
        hydride_ner.extract_hydride_parameters(parsed)


def test_hydride_values_use_shared_unit_and_exponent_parser():
    rec = clean_hydride_record(
        {
            "formula": "LaH10",
            "tc_kelvin": "1e-3 K",
            "pressure_gpa": "20 kbar",
            "mu_star": "0.10±0.02",
        }
    )
    assert rec is not None
    assert rec["tc_kelvin"] == 0.001
    assert rec["pressure_gpa"] == 2
    proposal = rec["provenance"]["extraction_proposal"]
    assert proposal["raw_extraction"]["pressure_gpa"] == "20 kbar"
    assert proposal["scientific_values"]["mu_star"]["uncertainty"] == 0.02


@pytest.mark.parametrize("tc", ["80–95 K", "<2 K", True, "1e999 K"])
def test_hydride_non_scalar_tc_has_no_parameter_row(tc):
    assert (
        clean_hydride_record({"formula": "LaH10", "tc_kelvin": tc, "pressure_gpa": "20 kbar"})
        is None
    )


def test_hydride_non_scalar_condition_survives_in_provenance():
    rec = clean_hydride_record(
        {"formula": "H3S", "tc_kelvin": "200 K", "pressure_gpa": "150–160 GPa", "lambda_eph": "2"}
    )
    assert rec is not None
    assert rec["pressure_gpa"] is None
    pressure = rec["provenance"]["extraction_proposal"]["scientific_values"]["pressure_gpa"]
    assert pressure["relation"] == "interval"
    assert (pressure["lower"], pressure["upper"]) == (150, 160)
    assert any("pressure_gpa" in flag for flag in rec["validation_flags"])


def test_hydride_isotope_notation_is_never_flattened_into_stoichiometry():
    raw = {
        "formula": "La2H10",
        "formula_raw": "La²H10",
        "tc_kelvin": "100 K",
        "pressure_gpa": "20 kbar",
    }
    assert clean_hydride_record(raw) is None
    proposal = hydride_ner.hydride_proposal(raw)
    assert proposal["formula_raw"] == "La²H10"
    assert hydride_ner._normalize_formula_text("La²H10") == "La²H10"


def test_hydride_source_omega_requires_unit_and_uses_software_conversion():
    rec = clean_hydride_record(
        {
            "formula": "LaH10",
            "tc_kelvin": "250 K",
            "pressure_gpa": "170 GPa",
            "omega_log_source_value": "100 meV",
        }
    )
    assert rec is not None
    assert rec["omega_log_source_value"] == pytest.approx(100)
    assert rec["omega_log_source_unit"] == "meV"
    assert rec["omega_log_k"] == pytest.approx(1160.45)
    no_unit = clean_hydride_record(
        {
            "formula": "LaH10",
            "tc_kelvin": "250 K",
            "pressure_gpa": "170 GPa",
            "omega_log_source_value": "100",
        }
    )
    assert no_unit["omega_log_k"] is None
    assert no_unit["provenance"]["extraction_proposal"]["scientific_values"][
        "omega_log_source_value"
    ]["errors"] == ["missing_source_unit"]


def test_extraction_batch_archives_every_structured_proposal_without_model_prose(monkeypatch):
    rows = [
        {
            "formula": "LaH10",
            "tc_kelvin": "80–95 K",
            "pressure_gpa": "20 kbar",
            "evidence_quote": "Do not retain this unrestricted model field.",
        },
        {"formula": "La²H10", "tc_kelvin": "100 K", "pressure_gpa": "20 kbar"},
        {"formula": "H3S", "tc_kelvin": "1e-3 K", "pressure_gpa": "20 kbar"},
    ]
    monkeypatch.setattr(
        hydride_ner,
        "_generate_content_with_retry",
        lambda *_args: SimpleNamespace(text=json.dumps(rows)),
    )
    parsed = ParsedPaper(
        meta=PaperMetadata(
            arxiv_id="2601.00001",
            title="Synthetic hydride",
            authors=[],
            abstract="Synthetic test",
            date_submitted=None,
            categories=[],
            primary_category=None,
        ),
        sections=[],
    )
    batch = hydride_ner.extract_hydride_parameters(parsed)
    assert len(batch) == 1
    assert len(batch.proposals) == 3
    assert [p["scalar_row_eligible"] for p in batch.proposals] == [False, False, True]
    assert batch.proposals[0]["raw_extraction"]["tc_kelvin"] == "80–95 K"
    assert "evidence_quote" not in batch.proposals[0]["raw_extraction"]
    assert batch.proposals[1]["formula_raw"] == "La²H10"


def test_oversized_model_field_is_hashed_not_cached_as_restricted_prose():
    proposal = hydride_ner.hydride_proposal({"formula": "LaH10", "tc_kelvin": "x" * 600})
    raw = proposal["raw_extraction"]["tc_kelvin"]
    assert raw["status"] == "oversized_structured_value_not_retained"
    assert len(raw["sha256"]) == 64
    assert proposal["scientific_values"]["tc_kelvin"]["status"] == "invalid"
