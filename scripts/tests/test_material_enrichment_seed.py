"""Packaged source candidates never follow a changed or excluded occurrence."""
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from services import material_enrichment_seed as seeds  # noqa: E402
from services.material_enrichment import build_enrichment_report, digest, text_digest  # noqa: E402


def fixture():
    records = [{"formula": "NbN", "paper_id": "paper:1", "tc_kelvin": 16}]
    material = SimpleNamespace(id="mat:nbn", formula="NbN", current_records=lambda: records)
    text = "Computed NbN has Tc=16 K at 2 GPa."
    source = {"id": "primary:1", "paper_id": "paper:1", "text": text,
              "content_sha256": text_digest(text), "source_revision": "synthetic-source/v1",
              "kind": "original_passage", "locator": {"section": "Synthetic fixture"}}
    report = build_enrichment_report([{"id": material.id, "formula": material.formula, "records": records}],
                                     [source], include_evidence_text=False)
    seed = {"version": "materials-enrichment-seed/1.0.0", "seed_id": "synthetic-test", "seed_sha256": "0" * 64,
            "reports": [report]}
    blank = build_enrichment_report([{"id": material.id, "formula": material.formula, "records": records}], [],
                                    include_evidence_text=False)
    return material, records, seed, blank


def test_actual_packaged_seed_is_metadata_only_validated_and_complete():
    seeds.load_seed.cache_clear()
    seed = seeds.load_seed()
    assert seed is not None
    assert seeds._metadata_only(seed)
    candidates = [c for r in seed["reports"] for c in r["candidates"]]
    assert len(candidates) == 39
    assert seed["extractor_version"] == "materials-literal-extractor/1.0.1"
    assert all(c["extractor_version"] == seed["extractor_version"] for c in candidates)
    forms = [c for c in candidates if c["field"] == "sample_form"]
    assert len(forms) == 4
    assert all(c["value"] == "single_crystal" for c in forms)
    assert not any(c["source"]["capture_id"] in {
        "primary:arxiv:0912.2752:16", "primary:arxiv:0912.2752:20"
    } for c in forms)
    assert sum(c["quantity"] is not None for c in candidates) == 14
    assert seed["seed_sha256"] == digest({k: v for k, v in seed.items() if k != "seed_sha256"})


def test_current_exact_reference_merges_without_promotion_or_seed_mutation(monkeypatch):
    material, _, seed, blank = fixture()
    original = deepcopy(seed)
    monkeypatch.setattr(seeds, "load_seed", lambda: seed)
    result = seeds.merge_primary_seed(blank, material)
    assert result["primary_source_seed"]["candidate_facts_added"] > 0
    assert result["counts"]["promoted_facts"] == 0
    assert result["scientific_acceptance"] is False
    assert result["report_sha256"] == digest({k: v for k, v in result.items() if k != "report_sha256"})
    pressure = next(f for f in result["coverage"][0]["fields"] if f["field"] == "pressure_gpa")
    assert pressure["status"] == "pending_review"
    result["candidates"][0]["raw_value"] = "caller mutation"
    assert seed == original


def test_replaced_record_or_excluded_source_cannot_receive_old_candidates(monkeypatch):
    material, records, seed, blank = fixture()
    monkeypatch.setattr(seeds, "load_seed", lambda: seed)
    records[0]["tc_kelvin"] = 17
    assert seeds.merge_primary_seed(deepcopy(blank), material)["candidates"] == []
    material.current_records = lambda: []
    assert seeds.merge_primary_seed(deepcopy(blank), material)["candidates"] == []


def test_formula_identity_and_every_reference_must_be_current(monkeypatch):
    material, _, seed, blank = fixture()
    monkeypatch.setattr(seeds, "load_seed", lambda: seed)
    material.formula = "Nb2N"
    assert seeds.merge_primary_seed(deepcopy(blank), material)["candidates"] == []
    material.formula = "NbN"
    for candidate in seed["reports"][0]["candidates"]:
        candidate["retained_result_refs"].append({"result_id": "gone", "record_sha256": "0" * 64})
    assert seeds.merge_primary_seed(deepcopy(blank), material)["candidates"] == []
