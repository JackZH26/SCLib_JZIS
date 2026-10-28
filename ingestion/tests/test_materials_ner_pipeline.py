"""Meaningful offline controls for the new extraction and recovery boundary."""
import json
import time
from copy import deepcopy

import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import Extraction, Quantity, canonical, output_schema
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.sources import (
    Bundle, Document, inspect_chunks, make_blocks, parse_local, save_bundle, verify_bundle,
)
from ingestion.materials_ner.store import LostLease, Store
from ingestion.materials_ner.validation import (
    normalize, quantity_source_issues, training_exclusions, validate_extraction,
)
from ingestion.materials_ner.contract import Evidence
from ingestion.materials_ner.worker import configuration, export_review_packet, run_one

TEXT = ("SYNTHETIC TEST FIXTURE, not a scientific source. "
        "Sample A was nominal MgB2 in bulk form. "
        "For Sample A, at a measurement pressure of 20 kbar, a four-probe resistivity measurement "
        "found a zero-resistance superconducting transition at 39 K. "
        "This was our own measured result, rather than a cited result.")
SAMPLE_QUOTE = "Sample A was nominal MgB2 in bulk form."
RESULT_QUOTE = ("For Sample A, at a measurement pressure of 20 kbar, a four-probe resistivity measurement "
                "found a zero-resistance superconducting transition at 39 K.")


def quantity(value=39.0, unit="K", raw="39 K", **kwargs):
    return {"status": "reported", "raw": raw, "relation": "exact", "value": value,
            "lower": None, "upper": None, "unit": unit, "approximate": False,
            "uncertainty": None, **kwargs}


def example():
    block = make_blocks("doc:synthetic", [("synthetic:1", TEXT)])[0]
    bundle = Bundle(
        version="materials-source-bundle/1", work_id="synthetic:example", title="SYNTHETIC",
        family="synthetic", source_status="unresolved", supplement_status="not_checked",
        documents=[Document(id="doc:synthetic", source_uri="synthetic:fixture", source_sha256="0" * 64,
                            source_kind="original_text", role="main", publication_version=None,
                            version_status="unresolved", processing_permission="allowed",
                            redistribution_permission="unresolved", coverage="complete_document",
                            parser="synthetic")], blocks=[block], acquisition_notes=["SYNTHETIC"])

    def evidence(fields, quote=RESULT_QUOTE):
        return [{"block_id": block.id, "quote": quote, "field": field} for field in fields]
    extraction = {
        "schema_version": "materials-ner/1", "work_id": bundle.work_id, "outcome": "results",
        "empty_reason": None, "processed_block_ids": [block.id], "unread_block_ids": [], "limitations": [],
        "samples": [{"id": "s1", "label": "A", "formula_raw": "MgB2", "composition_basis": "nominal",
                     "identity_resolution": "source_scoped", "target_kind": "bulk", "form_raw": "bulk",
                     "substrate_raw": None, "isotopes": [], "variables": [],
                     "evidence": evidence(["/formula_raw", "/composition_basis"], SAMPLE_QUOTE)}],
        "states": [{"id": "st1", "sample_id": "s1", "label": None, "preparation_raw": None,
                    "conditions": [{"kind": "pressure", "role": "measurement",
                                    "quantity": quantity(20.0, "kbar", "20 kbar"),
                                    "orientation_raw": None, "basis_raw": None}],
                    "evidence": evidence(["/sample_id", "/conditions/0"])}],
        "protocols": [{"id": "p1", "method": "four-probe resistivity", "observable": "resistivity",
                       "criterion": "zero_resistance", "criterion_raw": "zero-resistance",
                       "details_raw": None, "evidence": evidence(["/method", "/criterion"])}],
        "results": [{"id": "r1", "sample_id": "s1", "state_id": "st1", "protocol_id": "p1",
                     "quantity_kind": "tc", "quantity": quantity(), "origin": "observed",
                     "quantity_name_raw": None,
                     "source_role": "primary", "component_raw": None, "interpretation_raw": None,
                     "cited_source_raw": None, "dependencies": [],
                     "evidence": evidence(["/quantity_kind", "/quantity", "/sample_id",
                                           "/state_id", "/protocol_id", "/origin", "/source_role"])}],
    }
    return bundle, extraction


def test_complete_event_preserves_pressure_conversion_and_stays_pending():
    bundle, raw = example()
    extraction = Extraction.model_validate(raw)
    report = validate_extraction(extraction, bundle)
    assert report["valid"], report["issues"]
    assert report["normalized"]["/states/0/conditions/0/quantity"]["normalized"]["value"] == 2
    assert report["scientific_acceptance"] is False
    assert training_exclusions(extraction, bundle, report)["results"][0]["eligible"] is False


@pytest.mark.parametrize("changes", [
    {"value": 0.0, "status": "not_reported"},
    {"relation": "interval", "value": 39.0, "lower": 1.0, "upper": 2.0},
    {"relation": "interval", "value": None, "lower": 2.0, "upper": 1.0},
    {"value": float("nan")}, {"value": float("inf")}, {"value": True},
])
def test_invalid_numeric_shapes_are_not_labels(changes):
    with pytest.raises(ValidationError):
        Quantity.model_validate(quantity(**changes))


def test_conflicting_source_values_can_retain_their_unit_without_selecting_a_number():
    q = Quantity.model_validate(quantity(status="conflicted", value=None, relation=None,
                                        raw="39.0 K in text; 38.9 K in table"))
    assert q.unit == "K" and normalize("tc", q)["normalized"] is None


@pytest.mark.parametrize(("relation", "values"), [
    ("lt", {"upper": 2.0}), ("ge", {"lower": 2.0}), ("interval", {"lower": 1.0, "upper": 2.0}),
])
def test_censoring_is_preserved(relation, values):
    q = Quantity.model_validate(quantity(value=None, relation=relation, **values))
    result = normalize("tc", q)["normalized"]
    assert result["relation"] == relation and "value" not in result


def test_cross_sample_binding_and_dependency_cycle_rejected():
    _, raw = example()
    second = deepcopy(raw["samples"][0])
    second["id"] = "s2"
    raw["samples"].append(second)
    raw["results"][0]["sample_id"] = "s2"
    with pytest.raises(ValidationError, match="cross-sample"):
        Extraction.model_validate(raw)
    raw["results"][0]["sample_id"] = "s1"
    other = deepcopy(raw["results"][0])
    other["id"] = "r2"
    raw["results"].append(other)
    raw["results"][0]["dependencies"] = [{"result_id": "r2", "relation": "derived_from"}]
    raw["results"][1]["dependencies"] = [{"result_id": "r1", "relation": "derived_from"}]
    with pytest.raises(ValidationError, match="cyclic"):
        Extraction.model_validate(raw)


def test_numeric_hallucination_cannot_pass_a_real_quote():
    bundle, raw = example()
    raw["results"][0]["quantity"]["value"] = 93.0
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert "numeric_value_disagrees_with_raw" in {i["code"] for i in report["issues"]}


def test_approximation_tilde_is_not_silently_removed_as_tex_whitespace():
    q = Quantity.model_validate(quantity(raw="~39 K", approximate=False))
    evidence = [Evidence(block_id="test", quote="Tc ~39 K.", field="/quantity")]
    assert quantity_source_issues("tc", q, evidence, "/quantity") == ["approximation_marker_lost"]
    exact = Quantity.model_validate(quantity(raw="39~K"))
    evidence = [Evidence(block_id="test", quote="Tc 39~K.", field="/quantity")]
    assert quantity_source_issues("tc", exact, evidence, "/quantity") == []


def test_fabricated_quote_and_missing_coverage_fail():
    bundle, raw = example()
    raw["results"][0]["evidence"][0]["quote"] = "Invented source sentence."
    raw["processed_block_ids"] = []
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert not report["valid"]
    assert "coverage_inventory_mismatch" in {i["code"] for i in report["issues"]}


def test_band_scale_is_not_ordinary_tc():
    bundle, raw = example()
    raw["results"][0]["component_raw"] = "pi band"
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert "band_or_fit_temperature_requires_model_scale_review" in {i["code"] for i in report["issues"]}


def test_out_of_registry_quantity_is_reviewable_without_forcing_it_to_tc():
    bundle, raw = example()
    result = raw["results"][0]
    result["quantity_kind"] = "unmapped"
    result["quantity_name_raw"] = "synthetic heat-capacity jump"
    result["quantity"]["unit"] = "mJ/(mol K)"
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert not report["valid"]
    assert "unregistered_quantity_requires_domain_review" in {i["code"] for i in report["issues"]}


def test_non_detection_requires_window_and_never_zero_tc():
    bundle, raw = example()
    raw["results"][0]["quantity_kind"] = "non_detection"
    report = validate_extraction(Extraction.model_validate(raw), bundle)
    assert {i["code"] for i in report["issues"]} >= {
        "non_detection_is_not_point_tc", "non_detection_window_missing"}


def test_applied_field_and_synthesis_pressure_do_not_make_measurement_pressure():
    bundle, raw = example()
    raw["states"][0]["conditions"][0]["role"] = "synthesis"
    extraction = Extraction.model_validate(raw)
    report = validate_extraction(extraction, bundle)
    assessment = training_exclusions(extraction, bundle, report)
    assert "measurement_pressure_unknown" in assessment["results"][0]["reason_codes"]


def test_aps_facts_and_abstracts_never_become_original_sources():
    result = inspect_chunks([{"id": "a", "section": "Facts", "text": "MgB2 Tc 39 K"},
                             {"id": "b", "section": "Abstract", "text": "Original abstract"}])
    assert not result["usable_original_passages"]
    assert result["kinds"] == {"derived_fact": 1, "abstract": 1}
    assert result["rejected"][0]["reason"] == "circular_old_ner_output"


def test_verified_passage_is_still_not_full_paper_coverage():
    bundle, _ = example()
    block = bundle.blocks[0]
    report = inspect_chunks([{"id": "c", "text": block.text, "evidence": {
        "chunk_kind": "original_passage", "content_sha256": block.sha256,
        "source_capture_id": "capture", "source_locator": {"page": 1},
        "permission_status": "allowed", "currentness": "current"}}])
    assert report["usable_original_passages"] == ["c"]
    assert not report["full_paper_coverage_verified"]


def test_no_16000_character_truncation(tmp_path):
    text = "SYNTHETIC source.\n" * 3000 + "END-OF-SOURCE-RESULT"
    path = tmp_path / "source.txt"
    path.write_text(text)
    bundle = parse_local(path, work_id="synthetic:long", title="Synthetic",
                         source_uri="synthetic:long", processing_permission="allowed")
    assert bundle.blocks[0].text == text
    assert bundle.blocks[0].text.endswith("END-OF-SOURCE-RESULT")
    changed = bundle.model_copy(deep=True)
    changed.blocks[0].text += "tamper"
    with pytest.raises(ValueError, match="integrity"):
        verify_bundle(changed)


def test_schema_accepts_complete_fixture_and_forbids_extra_acceptance():
    import jsonschema
    _, raw = example()
    jsonschema.validate(raw, output_schema())
    raw["scientific_acceptance"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, output_schema())


def enqueue_example(tmp_path):
    store = Store(tmp_path)
    bundle, extraction = example()
    bundle_hash, _ = save_bundle(store.root, bundle)
    config = configuration()
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=config)
    return store, job, bundle_hash, config, extraction


def test_duplicate_enqueue_and_crash_reclaim_do_not_accept_late_results(tmp_path):
    store, job_id, bundle_hash, config, _ = enqueue_example(tmp_path)
    assert store.enqueue(work_id="synthetic:example", bundle_hash=bundle_hash, config=config) == job_id
    first = store.claim(lease_seconds=1)
    assert store.claim() is None
    with store.connect() as db:
        db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job_id))
    second = Store(tmp_path).claim()
    assert second["lease_token"] != first["lease_token"]
    with pytest.raises(LostLease):
        store.finish(first, state="succeeded", receipt_path="old", receipt_hash="x",
                     usage={}, duration_seconds=1)
    store.finish(second, state="failed", receipt_path="new", receipt_hash="y",
                 usage={}, duration_seconds=1, error_code="simulated_failure")
    assert store.summary()["states"] == {"failed": 1}


class FakeProvider:
    def __init__(self, raw=None, fail=False):
        self.raw, self.fail = raw, fail

    def extract(self, prompt, schema, config, directory):
        if self.fail:
            raise ProviderFailure("simulated_timeout", retryable=False)
        value = self.raw
        if isinstance(value, dict) and value.get("schema_version") == "materials-ner/1":
            value = compact_fixture(value, catalog=json.loads((directory / "source-catalog.json").read_text()))
        return ProviderResult(canonical(value), {"input_tokens": 100, "output_tokens": 50},
                              "fake", config["model"], "synthetic:call", 0.01)


def compact_fixture(raw, bundle=None, catalog=None):
    """Synthetic provider transport fixture; never used to transform real outputs."""
    from ingestion.materials_ner.evidence import source_catalog
    catalog = catalog or source_catalog(bundle or example()[0])
    aliases = {block["block_id"]: alias for alias, block in catalog["blocks"].items()}
    def entity(value, excluded):
        result = {k: v for k, v in deepcopy(value).items() if k not in set(excluded) | {"evidence"}}
        references = {}
        for ev in value["evidence"]:
            # Tests use small synthetic blocks; never rebind real model output.
            key = next(identifier for identifier, span in catalog["spans"].items()
                       if span["block_id"] == ev["block_id"] and ev["quote"] in span["text"])
            references.setdefault(key, []).append(ev["field"])
        result["evidence"] = [{"span_ids": [key], "fields": fields} for key, fields in references.items()]
        return result
    samples = {x["id"]: x for x in raw["samples"]}
    states = {x["id"]: x for x in raw["states"]}
    protocols = {x["id"]: x for x in raw["protocols"]}
    observations = [{
        "id": r["id"], "sample": entity(samples[r["sample_id"]], {"id"}),
        "state": entity(states[r["state_id"]], {"id", "sample_id"}),
        "protocol": entity(protocols[r["protocol_id"]], {"id"}),
        "result": entity(r, {"id", "sample_id", "state_id", "protocol_id"}),
    } for r in raw["results"]]
    return {"work_id": raw["work_id"], "limitations": raw["limitations"],
            **{k: [aliases[v] for v in raw[k]] for k in ("processed_block_ids", "unread_block_ids")},
            "schema_version": "materials-ner-compact/3",
            "completion": {k: raw[k] for k in ("outcome", "empty_reason")},
            "observations": observations}


def test_worker_failure_is_not_success_empty(tmp_path):
    store, job, *_ = enqueue_example(tmp_path)
    result = run_one(store, job_id=job, provider_override=FakeProvider(fail=True))
    assert result["state"] == "failed"
    assert store.summary()["states"] == {"failed": 1}


def test_worker_and_packet_keep_pending_state_and_failed_denominator(tmp_path):
    store, job, _, _, extraction = enqueue_example(tmp_path / "state")
    result = run_one(store, job_id=job, provider_override=FakeProvider(extraction))
    assert result["state"] == "succeeded"
    export_review_packet(store, tmp_path / "review")
    manifest = json.loads((tmp_path / "review/manifest.json").read_text())
    assert manifest["jobs"][0]["result_count"] == 1
    assert manifest["scientific_acceptance"] is False
    assert manifest["ml_training_eligible"] is False
    assert run_one(store, provider_override=FakeProvider(extraction)) is None


def test_invalid_model_output_is_quarantined_and_keeps_raw(tmp_path):
    store, job, *_ = enqueue_example(tmp_path)
    result = run_one(store, job_id=job, provider_override=FakeProvider({"wrong": "contract"}))
    assert result["state"] == "quarantined"
    assert len(list(tmp_path.glob("attempts/*/*/output.json"))) == 1


def test_review_export_detects_raw_output_tampering(tmp_path):
    store, job, _, _, extraction = enqueue_example(tmp_path / "state")
    run_one(store, job_id=job, provider_override=FakeProvider(extraction))
    next((tmp_path / "state").glob("attempts/*/*/output.json")).write_text("{}")
    with pytest.raises(ValueError, match="raw output integrity"):
        export_review_packet(store, tmp_path / "review")


def test_prompt_contract_change_requires_a_new_job(tmp_path):
    store, job, *_ = enqueue_example(tmp_path)
    with store.connect() as db:
        row = db.execute("SELECT config_json FROM jobs WHERE id=?", (job,)).fetchone()
        config = json.loads(row[0])
        config["prompt_sha256"] = "bad"
        db.execute("UPDATE jobs SET config_json=? WHERE id=?", (canonical(config), job))
    result = run_one(store, job_id=job, provider_override=FakeProvider(fail=True))
    assert result["error_code"] == "worker_contract_drift"
