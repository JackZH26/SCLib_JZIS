from __future__ import annotations

from ingestion.extract.materials_aggregator import (
    _derive_summary,
    _paper_source_label,
)


def test_paper_source_label_formats_known_sources():
    assert _paper_source_label("arxiv:2510.12345") == "arXiv:2510.12345"
    assert _paper_source_label("arxiv:cond-mat/0500001") == "arXiv:cond-mat/0500001"
    assert _paper_source_label("aps:10.1103/PhysRevB.1.1") == "DOI: 10.1103/PhysRevB.1.1"
    assert _paper_source_label("doi:10.1103/PhysRevB.1.1") == "DOI: 10.1103/PhysRevB.1.1"
    assert _paper_source_label("nims:MgB2") == "NIMS:MgB2"
    assert _paper_source_label("custom:paper") == "custom:paper"
    assert _paper_source_label("") is None
    assert _paper_source_label(None) is None


def test_tc_max_conditions_formats_aps_paper_id():
    summary = _derive_summary(
        "CsV3Sb5-xNbx",
        [{
            "formula": "CsV3Sb5-xNbx",
            "tc_kelvin": 4.4,
            "pressure_gpa": 0.0,
            "measurement": "resistivity",
            "sample_form": "single crystal",
            "evidence_type": "primary_experimental",
            "confidence": 0.95,
            "paper_id": "aps:10.1103/j98r-9m59",
        }],
    )

    assert summary["tc_max_conditions"] == (
        "ambient, single crystal, resistivity, DOI: 10.1103/j98r-9m59"
    )


def test_tc_max_conditions_keeps_arxiv_paper_id():
    summary = _derive_summary(
        "MgB2",
        [{
            "formula": "MgB2",
            "tc_kelvin": 39.0,
            "pressure_gpa": 0.0,
            "measurement": "susceptibility",
            "evidence_type": "primary_experimental",
            "confidence": 0.95,
            "paper_id": "arxiv:0101446",
        }],
    )

    assert summary["tc_max_conditions"] == (
        "ambient, susceptibility, arXiv:0101446"
    )
