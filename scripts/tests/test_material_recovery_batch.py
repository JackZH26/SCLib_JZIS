"""Pending batch metadata is bound to unchanged source occurrences, never approval."""
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from services import material_recovery_batch_seed as seeds  # noqa: E402
from services.material_anomalies import _archive_record  # noqa: E402
from services.material_enrichment import (  # noqa: E402
    build_enrichment_report, build_record_field_coverage, digest, text_digest,
)
from services.property_evidence import legacy_result_id  # noqa: E402

spec = importlib.util.spec_from_file_location("batch_builder", ROOT / "scripts/build_materials_recovery_batch.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def rule_for(candidate):
    return {"candidate_id": candidate["candidate_id"], "paper_id": candidate["source"]["paper_id"],
            "capture_id": candidate["source"]["capture_id"], "page": candidate["source"]["locator"]["page"],
            "field": candidate["field"], "value": candidate["value"], "expected_subject": deepcopy(candidate["subject"])}


def bind_coverage(material, review):
    coverage = build_record_field_coverage(material["id"], material["records"])
    material["record_coverage"] = coverage
    review["rows"][0]["record_coverage_sha256"] = coverage["coverage_sha256"]
    return material, review


def fixture():
    records = [{"formula": "NbN", "paper_id": "arxiv:2501.12345", "tc_kelvin": 16,
                "ambient_sc": True, "paper_type": "experimental", "credibility_tier": "T1", "tc_regime": "unknown"}]
    material = {"id": "mat:nbn", "formula": "NbN", "records": records}
    text = "NbN has Tc=16 K at 2 GPa. The pressure is reported for this synthetic test."
    source = {"id": "primary:test", "paper_id": records[0]["paper_id"], "text": text,
              "kind": "original_passage", "content_sha256": text_digest(text),
              "capture_sha256": "a" * 64, "source_revision": "arxiv:2501.12345v1",
              "source_status": "unknown", "source_url": "https://arxiv.org/pdf/2501.12345v1",
              "locator": {"page": 1, "section": "Synthetic fixture"}}
    extracted = build_enrichment_report([material], [source], include_evidence_text=False)
    candidate = next(c for c in extracted["candidates"] if c["field"] == "pressure_gpa" and c["value"] == 2)
    review = {"rows": [{"material_id": material["id"], "candidate_rules": [rule_for(candidate)],
              "summary": "Synthetic test only", "unknowns": ["Sample association unresolved"],
              "observations": [["pressure_scope", "Pressure", "2 GPa", 1, "at 2 GPa", "Observed", "Synthetic source scope"]]}]}
    bind_coverage(material, review)
    batch = builder.build([material], [source], review)
    blank = build_enrichment_report([material], [], include_evidence_text=False)
    model = SimpleNamespace(id=material["id"], formula=material["formula"], current_records=lambda: records)
    return model, records, batch, blank


def test_actual_batch_counts_and_source_authority_are_explicit():
    seeds.load_batch.cache_clear()
    batch = seeds.load_batch()
    assert batch is not None
    assert batch["counts"] == {"checked_materials": 16, "available_materials": 16,
                               "source_observations": 55, "pending_candidate_facts": 34,
                               "canonical_facts_changed": 0, "approved_facts": 0}
    assert len({r["material_id"] for r in batch["rows"]}) == 16
    assert all(r["counts"]["candidate_facts"] == len(r["candidates"]) for r in batch["reports"])
    encoded = json.dumps(batch)
    assert all(token not in encoded for token in ("/Users/", "source.pdf", "evidence_text\":", "page-texts"))
    for row in batch["rows"]:
        assert row["scientific_acceptance"] is row["human_reviewed"] is row["database_changed"] is False
        assert all(o["sample_association_status"] == "pending" for o in row["observations"])
    # Existing 39-fact primary seed remains an independent unchanged source.
    old = json.loads((ROOT / "api/services/resources/material_enrichment_seed.json").read_text())
    assert sum(len(r["candidates"]) for r in old["reports"]) == 39


def test_adjacent_h10_pressure_and_crb2_af_substudy_max_are_not_admitted():
    seeds.load_batch.cache_clear()
    batch = seeds.load_batch()
    candidates = [c for r in batch["reports"] for c in r["candidates"]]
    # Whole-page extraction linked the following H10 183 GPa expression to
    # H6's 237 K. Preserve the inspected H6 observation, reject that candidate.
    assert not any(c["material_id"] == "mat:layh6" for c in candidates)
    h6 = next(r for r in batch["rows"] if r["material_id"] == "mat:layh6")
    assert "237" in json.dumps(h6["observations"])
    assert any("pressure" in s.lower() for s in h6["unknowns"])
    # 12 GPa belongs to the AF hydrostatic experiment, not the paper-wide
    # superconductivity study reaching approximately 100 GPa.
    assert not any(c["material_id"] == "mat:crb2" and c["field"] == "maximum_applied_pressure_source_value" for c in candidates)
    cr = next(r for r in batch["rows"] if r["material_id"] == "mat:crb2")
    assert "100 GPa" in json.dumps(cr["observations"])


def test_exact_current_binding_is_idempotent_and_does_not_mutate_seed(monkeypatch):
    material, _, batch, blank = fixture()
    original = deepcopy(batch)
    monkeypatch.setattr(seeds, "load_batch", lambda: batch)
    merged = seeds.merge_recovery_batch(blank, material)
    first = deepcopy(merged)
    assert merged["source_recovery_batch"]["observations"] == batch["rows"][0]["observations"]
    assert merged["counts"]["candidate_facts"] == 1
    assert merged["counts"]["promoted_facts"] == 0
    assert seeds.merge_recovery_batch(merged, material) == first
    assert merged["report_sha256"] == digest({k: v for k, v in merged.items() if k != "report_sha256"})
    merged["source_recovery_batch"]["observations"][0]["value"] = "caller mutation"
    assert batch == original


def test_changed_excluded_or_wrong_formula_cannot_get_inspection_notes(monkeypatch):
    material, records, batch, blank = fixture()
    monkeypatch.setattr(seeds, "load_batch", lambda: batch)
    records[0]["tc_kelvin"] = 17
    assert seeds.merge_recovery_batch(deepcopy(blank), material) == blank
    material.current_records = lambda: []
    assert seeds.merge_recovery_batch(deepcopy(blank), material) == blank
    material.formula = "Nb2N"
    assert seeds.merge_recovery_batch(deepcopy(blank), material) == blank


@pytest.mark.parametrize("change", ["authority", "span", "paper", "origin", "counts", "private_text"])
def test_resealed_invalid_batch_is_refused(monkeypatch, tmp_path, change):
    _, _, batch, _ = fixture()
    row, obs = batch["rows"][0], batch["rows"][0]["observations"][0]
    if change == "authority":
        row["human_reviewed"] = True
    elif change == "span":
        obs["source"]["span"]["char_end"] = -1
    elif change == "paper":
        obs["source"]["paper_id"] = "unbound"
    elif change == "origin":
        obs["knowledge_origin"] = "Confirmed"
    elif change == "counts":
        batch["counts"]["approved_facts"] = 1
    else:
        obs["source"]["text"] = "full source text must not ship"
    batch["seed_sha256"] = digest({k: v for k, v in batch.items() if k != "seed_sha256"})
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(batch))
    monkeypatch.setattr(seeds, "SEED_PATH", path)
    seeds.load_batch.cache_clear()
    assert seeds.load_batch() is None
    seeds.load_batch.cache_clear()


@pytest.mark.parametrize("change", ["extra_pressure", "source_identity"])
def test_review_rule_rejects_unreviewed_conditions_and_source_identity(monkeypatch, change):
    material, records, batch, _ = fixture()
    candidate = deepcopy(batch["reports"][0]["candidates"][0])
    rule = rule_for(candidate)
    if change == "extra_pressure":
        candidate["subject"]["pressure_quantity"] = {"value": 183, "unit": "GPa"}
        error = "selected_literal_conditions_changed"
    else:
        candidate["source"]["capture_id"] = "another-page-capture"
        error = "selected_literal_or_source_identity_changed"
    monkeypatch.setattr(builder, "build_enrichment_report", lambda *args, **kwargs: {"candidates": [candidate]})
    payload, review = bind_coverage({"id": material.id, "formula": material.formula, "records": records},
                                  {"rows": [{"material_id": material.id, "candidate_rules": [rule]}]})
    with pytest.raises(ValueError, match=error):
        builder.build([payload], [], review)


def test_repeated_span_on_the_same_page_requires_explicit_resolution():
    text = "NbN at 2 GPa. NbN at 2 GPa."
    material, review = bind_coverage(
        {"id": "mat:nbn", "formula": "NbN", "records": [{"paper_id": "paper:test"}]},
        {"rows": [{"material_id": "mat:nbn", "candidate_rules": [],
                   "observations": [["pressure", "Pressure", "2 GPa", 1, "at 2 GPa", "Observed", "Synthetic"]]}]},
    )
    with pytest.raises(ValueError, match="source_span_not_unique"):
        builder.build([material],
                      [{"id": "source:test", "paper_id": "paper:test", "text": text,
                        "content_sha256": text_digest(text), "source_revision": "test", "kind": "original_passage", "locator": {"page": 1}}],
                      review)


def test_lossy_archive_cannot_supply_full_record_bindings():
    material, records, batch, _ = fixture()
    full = {"id": material.id, "formula": material.formula, "records": records}
    full, review = bind_coverage(full, {"rows": [{"material_id": material.id}]})
    projected = _archive_record(records[0])
    assert set(records[0]) - set(projected) == {"ambient_sc", "paper_type", "credibility_tier", "tc_regime"}
    assert legacy_result_id(projected, scope_id=material.id) != legacy_result_id(records[0], scope_id=material.id)
    assert digest(projected) != digest(records[0])
    assert builder.retained_bindings(full, review["rows"][0])[0] == batch["rows"][0]["retained_result_refs"][0]
    cropped = {**full, "records": [projected]}
    with pytest.raises(ValueError, match="retained_record_coverage_mismatch"):
        builder.retained_bindings(cropped, review["rows"][0])


@pytest.mark.parametrize("material_id", ["mat:nb4c3o2", "mat:ba3rh4ge16"])
def test_shipped_seed_matches_frozen_public_full_record_pins(material_id):
    # These public snapshots reproduce both the original zero-candidate window
    # failure and a four-occurrence paper with pending candidates. Do not derive
    # the expected IDs from the shipped seed or from its old lossy projection.
    public = json.loads((Path(__file__).parent / "fixtures/materials_recovery_binding_public_20261008.json").read_bytes())
    frozen = next(row for row in public["materials"] if row["id"] == material_id)
    records = frozen["records"]
    coverage = build_record_field_coverage(material_id, records)
    assert coverage["coverage_sha256"] == frozen["coverage_sha256"]
    assert [{key: row[key] for key in ("record_offset", "paper_id", "result_id", "record_sha256")}
            for row in coverage["records"]] == frozen["coverage_pins"]
    payload = {"id": material_id, "formula": frozen["formula"], "records": records, "record_coverage": coverage}
    pins = builder.retained_bindings(payload, {"record_coverage_sha256": frozen["coverage_sha256"]})
    seeds.load_batch.cache_clear()
    batch = seeds.load_batch()
    row = next(row for row in batch["rows"] if row["material_id"] == material_id)
    assert row["retained_result_refs"] == list(pins.values())
    blank = build_enrichment_report([payload], [], include_evidence_text=False)
    material = SimpleNamespace(id=material_id, formula=frozen["formula"], current_records=lambda: records)
    result = seeds.merge_recovery_batch(deepcopy(blank), material)
    assert result["source_recovery_batch"]["observations"] == row["observations"]
    assert result["counts"]["candidate_facts"] == row["pending_candidates"]
    material.current_records = lambda: [_archive_record(record) for record in records]
    assert seeds.merge_recovery_batch(deepcopy(blank), material) == blank


@pytest.mark.parametrize("change, error", [
    ("missing", "reviewed_record_coverage_required"),
    ("unreviewed_pin", "reviewed_record_coverage_required"),
    ("unsealed", "reviewed_record_coverage_required"),
    ("wrong_material", "reviewed_record_coverage_required"),
    ("authority", "reviewed_record_coverage_required"),
    ("stale_record", "retained_record_coverage_mismatch"),
    ("wrong_paper", "retained_record_coverage_mismatch"),
    ("wrong_id", "retained_record_coverage_mismatch"),
    ("wrong_hash", "retained_record_coverage_mismatch"),
    ("wrong_offset", "record_coverage_offset_mismatch"),
    ("boolean_offset", "record_coverage_offset_mismatch"),
    ("partial", "complete_record_coverage_required"),
    ("boolean_count", "complete_record_coverage_required"),
])
def test_stale_or_contradictory_coverage_fails_closed(change, error):
    material = {"id": "mat:test", "formula": "NbN", "records": [{"paper_id": "paper:test", "tc_kelvin": 16}]}
    material, review = bind_coverage(material, {"rows": [{"material_id": material["id"]}]})
    request, coverage = review["rows"][0], material["record_coverage"]
    if change == "missing":
        material.pop("record_coverage")
    elif change == "unreviewed_pin":
        request["record_coverage_sha256"] = "0" * 64
    elif change == "unsealed":
        coverage["records"][0]["paper_id"] = "paper:other"
    elif change == "stale_record":
        material["records"][0]["tc_kelvin"] = 17
    else:
        if change == "wrong_material":
            coverage["material_id"] = "mat:other"
        elif change == "authority":
            coverage["scientific_acceptance"] = True
        elif change == "wrong_paper":
            coverage["records"][0]["paper_id"] = "paper:other"
        elif change == "wrong_id":
            coverage["records"][0]["result_id"] = "legacy-result:" + "0" * 64
        elif change == "wrong_hash":
            coverage["records"][0]["record_sha256"] = "0" * 64
        elif change == "wrong_offset":
            coverage["records"][0]["record_offset"] = 1
        elif change == "boolean_offset":
            coverage["records"][0]["record_offset"] = False
        elif change == "partial":
            coverage["records_unchecked"] = 1
        elif change == "boolean_count":
            coverage["records_total"] = True
        coverage["coverage_sha256"] = digest({k: v for k, v in coverage.items() if k != "coverage_sha256"})
        request["record_coverage_sha256"] = coverage["coverage_sha256"]
    with pytest.raises(ValueError, match=error):
        builder.retained_bindings(material, request)


def test_same_paper_multiple_occurrences_require_correct_unique_offsets():
    material = {"id": "mat:test", "formula": "NbN", "records": [
        {"paper_id": "paper:test", "tc_kelvin": 15}, {"paper_id": "paper:test", "tc_kelvin": 16},
    ]}
    material, review = bind_coverage(material, {"rows": [{"material_id": material["id"]}]})
    coverage, request = material["record_coverage"], review["rows"][0]
    refs = builder.retained_bindings(material, request)
    assert refs[0]["paper_id"] == refs[1]["paper_id"] and refs[0]["record_sha256"] != refs[1]["record_sha256"]
    coverage["records"][1]["record_offset"] = 0
    coverage["coverage_sha256"] = digest({k: v for k, v in coverage.items() if k != "coverage_sha256"})
    request["record_coverage_sha256"] = coverage["coverage_sha256"]
    with pytest.raises(ValueError, match="record_coverage_offset_mismatch"):
        builder.retained_bindings(material, request)
