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
from services import material_recovery_batch_seed as seeds
from services.material_enrichment import build_enrichment_report, digest, text_digest

spec = importlib.util.spec_from_file_location("batch_builder", ROOT / "scripts/build_materials_recovery_batch.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def rule_for(candidate):
    return {"candidate_id": candidate["candidate_id"], "paper_id": candidate["source"]["paper_id"],
            "capture_id": candidate["source"]["capture_id"], "page": candidate["source"]["locator"]["page"],
            "field": candidate["field"], "value": candidate["value"], "expected_subject": deepcopy(candidate["subject"])}


def fixture():
    records = [{"formula": "NbN", "paper_id": "arxiv:2501.12345", "tc_kelvin": 16}]
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
    if change == "authority": row["human_reviewed"] = True
    elif change == "span": obs["source"]["span"]["char_end"] = -1
    elif change == "paper": obs["source"]["paper_id"] = "unbound"
    elif change == "origin": obs["knowledge_origin"] = "Confirmed"
    elif change == "counts": batch["counts"]["approved_facts"] = 1
    else: obs["source"]["text"] = "full source text must not ship"
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
    with pytest.raises(ValueError, match=error):
        builder.build([{"id": material.id, "formula": material.formula, "records": records}], [],
                      {"rows": [{"material_id": material.id, "candidate_rules": [rule]}]})


def test_repeated_span_on_the_same_page_requires_explicit_resolution():
    text = "NbN at 2 GPa. NbN at 2 GPa."
    with pytest.raises(ValueError, match="source_span_not_unique"):
        builder.build([{"id": "mat:nbn", "formula": "NbN", "records": [{"paper_id": "paper:test"}]}],
                      [{"id": "source:test", "paper_id": "paper:test", "text": text,
                        "content_sha256": text_digest(text), "source_revision": "test", "kind": "original_passage", "locator": {"page": 1}}],
                      {"rows": [{"material_id": "mat:nbn", "candidate_rules": [],
                                 "observations": [["pressure", "Pressure", "2 GPa", 1, "at 2 GPa", "Observed", "Synthetic"]]}]})
