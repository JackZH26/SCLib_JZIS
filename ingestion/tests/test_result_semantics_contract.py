"""Ingestion and export share the API's versioned scientific-origin golden cases."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from ingestion.claims.mapper import map_record_to_claim
from ingestion.extract.materials_aggregator import _derive_summary
from ingestion.result_semantics import annotate_record, classify_result, is_observed_result

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    (case["record"], case["knowledge_origin"], case["classification_status"], case["source_role"])
    for case in json.loads((ROOT / "docs/schemas/result-origin-v1.golden.json").read_text())
]

@pytest.mark.parametrize("record,origin,status,role", CASES)
def test_mapper_retains_shared_result_classification(record, origin, status, role):
    expected = classify_result(record)
    claim = map_record_to_claim(record, material_id="mat:test", source_snapshot_id=uuid.UUID(int=1))
    assert (expected.knowledge_origin, expected.classification_status, expected.source_role) == (origin, status, role)
    assert claim["extraction_metadata"]["result_classification"] == expected.as_dict()
    assert claim["raw_record"] == record
    assert (ROOT / "api/services/result_semantics.py").read_bytes() == (
        ROOT / "ingestion/ingestion/result_semantics.py"
    ).read_bytes()

def test_mixed_paper_and_missing_origin_do_not_pollute_observed_headline():
    records = [
        {"tc_kelvin": 10, "evidence_type": "primary_experimental", "paper_type": "mixed"},
        {"tc_kelvin": 80, "evidence_type": "primary_theoretical", "paper_type": "mixed"},
        {"tc_kelvin": 90, "paper_type": "experimental"},
    ]
    records = [{**record, "paper_id": "fixture:mixed"} for record in records]
    # Isolate origin semantics from the separate MgB2 50 K review reference.
    summary = _derive_summary("YBa2Cu3O7", records)
    assert summary["tc_max_experimental"] == 10
    assert summary["tc_max_theoretical"] == 80
    assert summary["tc_max"] == 10
    assert [is_observed_result(r) for r in records] == [True, False, False]


def test_source_tier_does_not_adjudicate_conflict_or_approve_export():
    record = {"evidence_type": "primary_theoretical", "measurement": "resistivity",
              "validity_status": "accepted", "tc_kelvin": 1, "credibility_tier": "T1"}
    claim = map_record_to_claim(record, material_id="mat:test", source_snapshot_id=uuid.UUID(int=1))
    assert claim["validity_status"] == "pending"
    assert "result_classification_conflict" in claim["extraction_metadata"]["warnings"]


def test_distinct_cited_origins_have_distinct_semantic_fingerprints():
    base = {"source_role": "cited", "tc_kelvin": 30}
    claims = [map_record_to_claim(
        {**base, "knowledge_origin": origin}, material_id="mat:test", source_snapshot_id=uuid.UUID(int=1),
    ) for origin in ("Observed", "Computed")]
    assert claims[0]["evidence_role"] == claims[1]["evidence_role"] == "cited"
    assert claims[0]["semantic_fingerprint"] != claims[1]["semantic_fingerprint"]


def test_aggregation_classification_does_not_change_raw_occurrence_identity():
    record = {"formula": "MgB2", "tc_kelvin": 30, "paper_id": "fixture:identity",
              "evidence_type": "primary_theoretical"}
    summary = _derive_summary("MgB2", [record])
    assert summary["records"] == [record]
    before, after = [map_record_to_claim(
        raw, material_id="mat:test", source_snapshot_id=uuid.UUID(int=1)
    ) for raw in (record, summary["records"][0])]
    assert before["id"] == after["id"]
    assert before["source_record_hash"] == after["source_record_hash"]


def test_api_annotation_round_trip_does_not_mint_an_occurrence():
    raw = {"formula": "MgB2", "tc_kelvin": 30, "evidence_type": "primary_theoretical"}
    claims = [map_record_to_claim(
        item, material_id="mat:test", source_snapshot_id=uuid.UUID(int=1)
    ) for item in (raw, annotate_record(raw), {**raw, "tc_kelvin": 31})]
    assert claims[0]["id"] == claims[1]["id"]
    assert claims[0]["source_record_hash"] == claims[1]["source_record_hash"]
    assert claims[0]["semantic_fingerprint"] == claims[1]["semantic_fingerprint"]
    assert claims[0]["id"] != claims[2]["id"]
