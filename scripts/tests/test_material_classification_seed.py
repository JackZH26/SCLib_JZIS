"""Packaged statement metadata is never authority or a changed-record backfill."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
from services import material_classification_seed as seeds  # noqa: E402
from services.material_enrichment import AUTHORITY, build_enrichment_report, digest, text_digest  # noqa: E402


@pytest.fixture(autouse=True)
def clear_resource_cache():
    seeds.load_seed.cache_clear()
    yield
    seeds.load_seed.cache_clear()


def fixture():
    records = [{"formula": "NbN", "paper_id": "paper:synthetic", "tc_kelvin": 16}]
    material = SimpleNamespace(id="mat:synthetic", formula="NbN", current_records=lambda: records)
    statement = "NbN exhibits charge order measured by neutron diffraction."
    source = {"id": "capture:synthetic", "paper_id": "paper:synthetic", "text": statement,
              "content_sha256": text_digest(statement), "source_revision": "synthetic-capture/v1",
              "kind": "original_passage", "locator": {"section": "Synthetic benchmark"}}
    payload = {"id": material.id, "formula": material.formula, "records": records}
    full = build_enrichment_report([payload], [source], include_evidence_text=False)
    assert len(full["classification_candidates"]) == 1
    seed = {"version": seeds.VERSION, "seed_id": "synthetic-classification-test",
            "source_text_included": False, "classification_extractor_version": seeds.EXTRACTOR_VERSION,
            "candidates": full["classification_candidates"], **AUTHORITY}
    seed["seed_sha256"] = digest(seed)
    blank = build_enrichment_report([payload], [], include_evidence_text=False)
    return material, records, seed, blank


def test_matching_statement_keeps_pending_authority_and_does_not_mutate_seed(monkeypatch):
    material, _, seed, blank = fixture()
    original = deepcopy(seed)
    monkeypatch.setattr(seeds, "load_seed", lambda: seed)
    result = seeds.merge_primary_classification_seed(blank, material)
    candidate, = result["classification_candidates"]
    assert candidate["disposition"] == "pending"
    assert all(candidate[key] is False for key in AUTHORITY)
    assert result["counts"]["promoted_facts"] == result["classification_counts"]["promoted_facts"] == 0
    assert result["classification_primary_source_seed"]["candidate_facts_added"] == 1
    assert result["classification_counts"]["primary_source_retained_references_added"] == 1
    field = next(row for row in result["coverage"][0]["fields"] if row["field"] == "reported_order")
    assert field["status"] == "pending_review" and field["candidate_count"] == 1
    assert result["report_sha256"] == digest({key: value for key, value in result.items() if key != "report_sha256"})
    candidate["claim"]["normalized_value"] = "caller mutation"
    assert seed == original


def test_changed_formula_record_or_any_excluded_reference_cannot_receive_statement(monkeypatch):
    material, records, seed, blank = fixture()
    monkeypatch.setattr(seeds, "load_seed", lambda: seed)
    records[0]["tc_kelvin"] = 17
    assert seeds.merge_primary_classification_seed(deepcopy(blank), material)["classification_candidates"] == []
    records[0]["tc_kelvin"] = 16
    material.formula = "Nb2N"
    assert seeds.merge_primary_classification_seed(deepcopy(blank), material)["classification_candidates"] == []
    material.formula = "NbN"
    seed["candidates"][0]["retained_result_refs"].append({"result_id": "gone", "record_sha256": "0" * 64})
    assert seeds.merge_primary_classification_seed(deepcopy(blank), material)["classification_candidates"] == []
    material.current_records = lambda: []
    assert seeds.merge_primary_classification_seed(deepcopy(blank), material)["classification_candidates"] == []


def test_statement_merges_idempotently_and_numeric_candidates_remain_separate(monkeypatch):
    material, _, seed, blank = fixture()
    numeric = [{"candidate_id": "numeric:synthetic"}]
    blank["candidates"] = deepcopy(numeric)
    monkeypatch.setattr(seeds, "load_seed", lambda: seed)
    first = seeds.merge_primary_classification_seed(blank, material)
    second = seeds.merge_primary_classification_seed(first, material)
    assert len(second["classification_candidates"]) == second["classification_counts"]["candidate_facts"] == 1
    assert second["classification_primary_source_seed"]["candidate_facts_added"] == 0
    assert second["candidates"] == numeric


@pytest.mark.parametrize("mutation", ["authority", "nested_private", "invalid_claim", "missing_refs", "duplicate"])
def test_resource_rejects_resigned_bad_metadata(tmp_path, monkeypatch, mutation):
    _, _, seed, _ = fixture()
    candidate = seed["candidates"][0]
    if mutation == "authority":
        candidate["scientific_acceptance"] = True
    elif mutation == "nested_private":
        candidate["subject"]["conditions"]["private_notes"] = "must not be served"
    elif mutation == "invalid_claim":
        candidate["claim"]["value_raw"] = "Private reviewer notes"
    elif mutation == "missing_refs":
        candidate.pop("retained_result_refs")
        candidate.pop("retained_reference_count")
    else:
        seed["candidates"].append(deepcopy(candidate))
    candidate["candidate_id"] = "classification:" + digest({key: value for key, value in candidate.items() if key not in {"candidate_id", "evidence_text"}})
    seed["seed_sha256"] = digest({key: value for key, value in seed.items() if key != "seed_sha256"})
    resource = tmp_path / "seed.json"
    resource.write_text(json.dumps(seed))
    monkeypatch.setattr(seeds, "SEED_PATH", resource)
    assert seeds.load_seed() is None


def test_loader_reads_valid_bounded_metadata_and_degrades_without_source_data(tmp_path, monkeypatch):
    material, _, seed, blank = fixture()
    resource = tmp_path / "seed.json"
    resource.write_text(json.dumps(seed))
    monkeypatch.setattr(seeds, "SEED_PATH", resource)
    assert seeds.load_seed() == seed
    seeds.load_seed.cache_clear()
    resource.write_bytes(b"x" * 1_000_001)
    assert seeds.load_seed() is None
    result = seeds.merge_primary_classification_seed(blank, material)
    assert result["classification_candidates"] == []
    assert result["classification_primary_source_seed"] == {"status": "unavailable", "candidate_facts_added": 0}
    assert result["database_changed"] is False


def test_actual_primary_metadata_retains_source_version_and_exact_refs_without_source_text():
    seed = seeds.load_seed()
    assert seed is not None and seeds._metadata_only(seed)
    assert len(seed["candidates"]) == 2
    assert seed["classification_extractor_version"] == seeds.EXTRACTOR_VERSION
    assert {candidate["material_id"] for candidate in seed["candidates"]} == {"mat:cs(v0.93nb0.07)3sb5"}
    for candidate in seed["candidates"]:
        assert candidate["source"]["paper_id"] == "arxiv:2411.18744"
        assert candidate["source"]["source_url"] == "https://arxiv.org/html/2411.18744v1"
        assert candidate["subject"]["binding_proposal"]["source"]["paper_id"] == candidate["source"]["paper_id"]
        assert candidate["retained_reference_count"] == len(candidate["retained_result_refs"]) == 2
        assert all(candidate[key] is False for key in AUTHORITY)
        assert candidate["disposition"] == "pending"
