"""Data-level aggregation regressions using realistic cross-paper records."""
from __future__ import annotations

from ingestion.extract.materials_aggregator import _derive_summary


def _record(
    paper_id: str,
    tc_kelvin: float,
    *,
    evidence_type: str = "primary_experimental",
    ambient_sc: bool = True,
    measurement: str = "resistivity",
) -> dict:
    return {
        "formula": "YBa2Cu3O7",
        "paper_id": paper_id,
        "tc_kelvin": tc_kelvin,
        "pressure_gpa": 0.0,
        "pressure_state": "explicit_ambient",
        "ambient_sc": ambient_sc,
        "evidence_type": evidence_type,
        "measurement": measurement,
        "confidence": 0.95,
        "credibility_tier": "T1",
        "year": 2024,
    }


def test_cross_paper_summary_separates_theory_and_flags_tc_disagreement():
    records = [
        _record("arxiv:2401.00001", 92.0),
        _record("aps:10.1103/example", 58.0),
        _record(
            "arxiv:2401.00003",
            155.0,
            evidence_type="primary_theoretical",
            ambient_sc=False,
            measurement="dft",
        ),
    ]

    summary = _derive_summary("YBa2Cu3O7", records)

    assert summary["family"] == "cuprate"
    assert summary["tc_max"] == 92.0
    assert summary["tc_max_experimental"] == 92.0
    assert summary["tc_max_theoretical"] == 155.0
    assert summary["tc_ambient"] == 92.0
    assert summary["total_papers"] == 3
    assert summary["disputed"] is True
    assert summary["pairing_symmetry"] == "d-wave"
    assert summary["needs_review"] is False


def test_numeric_outlier_is_retained_without_hiding_valid_material_properties():
    good = {
        **_record("arxiv:0101446", 39.0),
        "formula": "MgB2",
    }
    impossible = {
        **_record("arxiv:9999.99999", 290.0),
        "formula": "MgB2",
    }

    summary = _derive_summary("MgB2", [good, impossible])

    assert summary["family"] == "mgb2"
    assert summary["tc_max"] == 39.0
    assert summary["total_papers"] == 2  # catalogue provenance, not positive-Tc support
    assert summary["records"] == [good, impossible]
    assert summary["anomaly_review"]["counts"]["review_required"] == 1
    assert summary["needs_review"] is False


def test_duplicate_records_from_one_paper_do_not_inflate_paper_support():
    summary = _derive_summary(
        "YBa2Cu3O7",
        [
            _record("arxiv:2401.00001", 90.0),
            _record("arxiv:2401.00001", 93.0),
            _record("aps:10.1103/example", 91.0),
        ],
    )

    assert summary["tc_max"] == 93.0
    assert summary["total_papers"] == 2
    assert "confirmed by" not in summary["tc_max_conditions"]


def test_equal_maximum_from_two_papers_is_labelled_as_confirmed():
    summary = _derive_summary(
        "YBa2Cu3O7",
        [
            _record("arxiv:2401.00001", 93.0),
            _record("aps:10.1103/example", 93.0),
        ],
    )

    assert summary["total_papers"] == 2
    assert "confirmed by 2 papers" in summary["tc_max_conditions"]
