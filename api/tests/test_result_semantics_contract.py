"""Offline cross-surface scientific origin contract (no DB/client fixtures)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.search import AskSource, MaterialDetail, MaterialSummary, SearchMatch
from services.rag import RagSourceInput, _format_sources
from services.result_semantics import (
    CLASSIFIER_VERSION,
    annotate_record,
    checked_legacy_split,
    classify_result,
    evidence_classifications,
    headline_origin,
    is_observed_result,
    legacy_evidence_role,
)
from services.timeline_points import as_float, extract_timeline_points, is_theoretical

ROOT = Path(__file__).resolve().parents[2]

CASES = [
    (case["record"], case["knowledge_origin"], case["classification_status"], case["source_role"])
    for case in json.loads((ROOT / "docs/schemas/result-origin-v1.golden.json").read_text())
]


@pytest.mark.parametrize("record,origin,status,role", CASES)
def test_explicit_result_contract(record, origin, status, role):
    result = classify_result(record)
    assert (result.knowledge_origin, result.classification_status, result.source_role) == (origin, status, role)
    assert result.classifier_version == CLASSIFIER_VERSION
    annotated = annotate_record(record)
    assert {k: v for k, v in annotated.items() if k != "result_classification"} == record
    assert classify_result(annotated) == result


def test_independent_images_vendor_identical_versioned_source():
    assert (ROOT / "api/services/result_semantics.py").read_bytes() == (
        ROOT / "ingestion/ingestion/result_semantics.py"
    ).read_bytes()


@pytest.mark.parametrize("labels,origin,status,role", CASES)
def test_material_search_rag_timeline_match(labels, origin, status, role):
    record = {"formula": "MgB2", "tc_kelvin": 30, "year": 2025, **labels}
    expected = classify_result(record).as_dict()
    material = MaterialDetail.model_validate({
        "id": "mat:test", "formula": "MgB2", "formula_latex": None,
        "family": None, "subfamily": None, "tc_max": 30, "tc_max_conditions": None,
        "tc_ambient": None, "arxiv_year": 2025, "total_papers": 1,
        "status": "active", "crystal_structure": None, "records": [record],
    })
    search = SearchMatch(
        paper_id="fixture", arxiv_id=None, title="Synthetic contract fixture", authors=[],
        year=2025, date_submitted=None, relevance_score=1, matched_chunk="synthetic",
        matched_section=None, materials=[record], citation_count=0, material_family=None,
        has_equation=False, has_table=False,
    )
    ask = AskSource(index=1, paper_id="fixture", arxiv_id=None, title="Synthetic",
                    authors_short="", year=2025, section=None, snippet="", material_evidence=evidence_classifications([record]))
    prompt = json.loads(_format_sources([RagSourceInput(
        1, "fixture", "Synthetic", "", 2025, None, "Synthetic example", [record],
    )]))
    point = extract_timeline_points("mat:test", [record], {})[0]
    assert material.records[0]["result_classification"] == expected
    assert search.materials[0]["result_classification"] == expected
    assert ask.material_evidence[0]["result_classification"] == expected
    assert AskSource.model_validate(ask.model_dump()).material_evidence == ask.material_evidence
    assert prompt[0]["material_evidence"][0]["result_classification"] == expected
    assert (point.knowledge_origin, point.classification_status, point.source_role) == (origin, status, role)
    assert point.classifier_version == CLASSIFIER_VERSION
    assert point.is_theoretical == (origin == "Computed" and role != "conflicted")




def test_conflicting_origins_do_not_collapse_with_observations():
    records = [
        {"tc_kelvin": 5, "year": 2025},
        {"tc_kelvin": 5, "year": 2025, "evidence_type": "primary_experimental"},
        {"tc_kelvin": 5, "year": 2025, "evidence_type": "primary_theoretical", "method": "resistivity"},
    ]
    points = extract_timeline_points("mat:test", records, {})
    assert len(points) == 3
    assert len({p.id for p in points}) == 3


def test_legacy_role_never_infers_primary_from_a_method():
    assert legacy_evidence_role({"measurement": "resistivity"}) == "unknown"
    assert legacy_evidence_role({"measurement": "resistivity", "source_role": "primary"}) == "primary_experimental"
    assert is_theoretical({"evidence_type": "primary_theoretical", "pressure_gpa": None})
    assert not is_observed_result({"evidence_type": "primary_theoretical", "pressure_gpa": 0})






@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True])
def test_nonfinite_timeline_values_are_rejected(value):
    assert as_float(value) is None
    assert extract_timeline_points("mat:test", [{"tc_kelvin": value, "year": 2025}], {}) == []


def test_headline_with_untraceable_or_ambiguous_origin_stays_unknown():
    assert headline_origin([], 90) == "Unknown"
    assert headline_origin([{"tc_kelvin": 90, "knowledge_origin": "Computed"}], 90) == "Computed"
    assert headline_origin([
        {"tc_kelvin": 90, "knowledge_origin": "Computed"}, {"tc_kelvin": 90}
    ], 90) == "Unknown"


def test_material_list_orm_summary_does_not_trust_stale_aggregate_type():
    row = SimpleNamespace(
        id="mat:test", formula="MgB2", formula_latex=None, family=None,
        subfamily=None, tc_max=30, tc_max_conditions=None, tc_ambient=None,
        arxiv_year=2025, total_papers=1, status="active", dominant_evidence="experimental",
        tc_max_experimental=30, tc_max_theoretical=None,
        records=[{"tc_kelvin": 30, "evidence_type": "primary_theoretical"}],
    )
    summary = MaterialSummary.model_validate(row)
    # SC02 cannot borrow a Computed source for an experimental-pool headline.
    # The raw origin remains visible, but the unsupported selection is withheld.
    assert summary.tc_max is None
    assert summary.tc_max_origin == "Unknown"
    assert summary.result_origin_counts["Computed"] == 1
    assert summary.result_origin_counts["Observed"] == 0
    assert summary.result_classification_version == CLASSIFIER_VERSION
    assert summary.tc_max_experimental is None
    assert summary.tc_max_theoretical is None  # Do not invent a new aggregate.
    assert summary.dominant_evidence == "theoretical"


def test_new_citation_metadata_does_not_export_nested_source_payloads():
    metadata = evidence_classifications([{
        "formula": "MgB2", "knowledge_origin": "Computed",
        "raw_extraction": {"restricted_text": "CANARY_RESTRICTED"},
        "provenance": {"reviewer_email": "CANARY_PRIVATE"},
    }])[0]
    assert set(metadata) == {"formula", "result_classification"}
    assert "CANARY" not in json.dumps(metadata)
    assert metadata["result_classification"]["knowledge_origin"] == "Computed"


def test_legacy_boolean_and_oversized_numbers_cannot_support_a_split_value():
    for raw in (True, 10**400, float("inf"), float("nan")):
        records = [{"tc_kelvin": raw, "knowledge_origin": "Observed"}]
        assert headline_origin(records, 1) == "Unknown"
        assert checked_legacy_split(records, 1, "Observed") is None
