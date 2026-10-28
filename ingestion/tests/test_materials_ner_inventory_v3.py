"""Synthetic invariants for context retention and evidence-only patching."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner.contract import canonical,digest,parse_extraction,Quantity
from ingestion.materials_ner.evidence_patch import (EvidencePatch,apply_patch,build_targets,
    output_schema as patch_schema,verify_applied_patch)
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import import_packet,verify_packet
from ingestion.materials_ner.quantities import normalize
from ingestion.materials_ner.repair_selection import scientific_payload
from ingestion.materials_ner.sources import make_blocks,save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.wire_v3 import CompactExtractionV3,output_schema,validate_coverage
from ingestion.materials_ner.worker import configuration,run_one
from test_materials_ner_inventory_v2 import fixture as fixture_v2,SequenceProvider,codes
from test_materials_ner_pipeline import quantity


def fixture():
    bundle,inventory,compact=fixture_v2()
    compact["schema_version"]="materials-ner-compact/5"
    for c in compact["observations"][0]["state"]["conditions"]:c["window_position"]=None
    identifier=compact["observations"][0]["id"]
    inventory["context_assertions"]=[{"id":"C1","kind":"protocol","description":"Four-probe resistivity method for Sample A.","span_ids":["S1"]}]
    compact["context_dispositions"]=[{"context_id":"C1","resolution":"carried",
        "bindings":[{"observation_id":identifier,"entity":"protocol","field":"/method"}],"explanation":None}]
    return bundle,inventory,compact


def validate(compact,inventory,bundle):
    report=validate_extraction(compact.expand(bundle),bundle)
    report["issues"]+=validate_coverage(compact,Inventory.model_validate(inventory),bundle)["issues"]
    report["valid"]=not report["issues"]
    return report


def test_v3_context_and_sparse_condition_schema_expand_without_changing_v2():
    bundle,inventory,raw=fixture();jsonschema.validate(raw,output_schema(bundle))
    c=CompactExtractionV3.model_validate(raw)
    assert validate(c,inventory,bundle)["valid"]
    e=c.expand(bundle).model_dump()
    assert e["schema_version"]=="materials-ner/3" and parse_extraction(e).model_dump()==e
    from ingestion.materials_ner.wire_v2 import CompactExtractionV2
    b,_,old=fixture_v2();old_e=CompactExtractionV2.model_validate(old).expand(b).model_dump()
    assert parse_extraction(old_e).model_dump()==old_e
    assert "window_position" not in old_e["states"][0]["conditions"][0]


@pytest.mark.parametrize("mutation,code",[
    ("missing","context_disposition_not_closed"),("duplicate","context_disposition_not_closed"),
    ("null_field","context_binding_field_empty"),("empty_array","context_binding_field_empty"),
    ("missing_evidence","context_field_evidence_disconnected"),
])
def test_context_cannot_be_counted_as_retained_without_a_real_bound_field(mutation,code):
    bundle,inventory,raw=fixture()
    if mutation=="missing":raw["context_dispositions"]=[]
    if mutation=="duplicate":raw["context_dispositions"]*=2
    if mutation=="null_field":raw["observations"][0]["protocol"]["method"]=None
    if mutation=="empty_array":raw["context_dispositions"][0]["bindings"][0]["field"]="/parameters"
    if mutation=="missing_evidence":raw["observations"][0]["protocol"]["evidence"]=[]
    assert code in codes(validate_coverage(CompactExtractionV3.model_validate(raw),Inventory.model_validate(inventory),bundle))


def test_context_exclusion_requires_reason_and_is_not_scientific_coverage_proof():
    bundle,inventory,raw=fixture()
    raw["context_dispositions"][0].update(resolution="not_applicable",bindings=[],explanation="Context describes a different sample.")
    report=validate_coverage(CompactExtractionV3.model_validate(raw),Inventory.model_validate(inventory),bundle)
    assert report["valid"] and len(report["context_exclusions"])==1
    assert not report["context_exclusions_independently_reviewed"] and not report["source_semantic_coverage_verified"]
    raw["context_dispositions"][0]["explanation"]=None
    assert "context_disposition_shape_invalid" in codes(validate_coverage(CompactExtractionV3.model_validate(raw),Inventory.model_validate(inventory),bundle))


def test_detection_window_has_measurement_extent_not_an_opposite_tc_bound():
    bundle,_,raw=fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",bundle.blocks[0].text+" Measurements reached 1.9 K.")])
    state=raw["observations"][0]["state"]
    state["conditions"].append({"kind":"temperature","role":"detection_window","quantity":quantity(1.9,"K","1.9 K"),
        "orientation_raw":None,"basis_raw":"Lowest measured temperature","window_position":"lower_limit"})
    state["evidence"][0]["fields"].append("/conditions/1")
    assert validate_extraction(CompactExtractionV3.model_validate(raw).expand(bundle),bundle)["valid"]
    state["conditions"][1]["quantity"].update(relation="lt",value=None,upper=1.9)
    assert "detection_window_bound_direction_conflict" in codes(validate_extraction(CompactExtractionV3.model_validate(raw).expand(bundle),bundle))
    state["conditions"][1]["window_position"]=None
    assert "detection_window_position_missing" in codes(validate_extraction(CompactExtractionV3.model_validate(raw).expand(bundle),bundle))


def test_registry_preserves_resistance_percent_radius_and_per_atom_dos_basis():
    ratio=normalize("resistance_fraction",Quantity.model_validate(quantity(90,"%","90%")))
    assert ratio["normalized"]["value"]==.9
    assert normalize("radius",Quantity.model_validate(quantity(2,"mm","2 mm")))["normalized"]["value"]==2e6
    assert normalize("gl_parameter",Quantity.model_validate(quantity(15.31,"1","15.31")))["normalized"]["value"]==15.31
    assert normalize("electronic_dos_per_atom",Quantity.model_validate(quantity(.133,"states/(eV atom)","0.133")))["normalized"]["unit"]=="states/(eV atom)"
    with pytest.raises(ValueError,match="unregistered_unit"):
        normalize("electronic_dos_per_atom",Quantity.model_validate(quantity(.133,"states/eV","0.133")))
    with pytest.raises(ValueError,match="fraction_outside_unit_interval"):
        normalize("resistance_fraction",Quantity.model_validate(quantity(110,"%","110%")))


def patch_fixture():
    bundle,inventory,raw=fixture()
    raw["observations"][0]["protocol"]["evidence"][0]["fields"].remove("/method")
    c=CompactExtractionV3.model_validate(raw);v=validate(c,inventory,bundle);targets=build_targets(c,v)
    patch={"schema_version":"materials-evidence-patch/1","work_id":bundle.work_id,
        "base_compact_sha256":digest(c.model_dump()),"decisions":[{"target_id":t["id"],"resolution":"bound","span_ids":["S1"],"reason":None} for t in targets]}
    return bundle,inventory,raw,c,targets,patch


def test_patch_only_repairs_requested_references_and_cannot_supply_scientific_replacements():
    bundle,inventory,raw,c,targets,p=patch_fixture()
    jsonschema.validate(p,patch_schema(bundle,c,targets))
    candidate,checks=apply_patch(c,EvidencePatch.model_validate(p),targets,bundle)
    assert scientific_payload(c)==scientific_payload(candidate) and checks["scientific_fields_unchanged"]
    assert validate(candidate,inventory,bundle)["valid"]
    assert c.observations[0].result==candidate.observations[0].result
    p["decisions"][0]["value"]=93
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(p,patch_schema(bundle,c,targets))


@pytest.mark.parametrize("mutation",["base","missing_target","duplicate_target","unknown_span","remove_present"])
def test_patch_rejects_drift_unaccounted_targets_and_unrelated_operations(mutation):
    bundle,_,_,c,targets,p=patch_fixture()
    if mutation=="base":p["base_compact_sha256"]="0"*64
    if mutation=="missing_target":p["decisions"]=[]
    if mutation=="duplicate_target":p["decisions"]*=2
    if mutation=="unknown_span":p["decisions"][0]["span_ids"]=["S999"]
    if mutation=="remove_present":p["decisions"][0].update(resolution="remove_invalid_pointer",span_ids=[],reason="Must not delete a real method.")
    with pytest.raises(ValueError):apply_patch(c,EvidencePatch.model_validate(p),targets,bundle)


def test_unsupported_patch_preserves_original_failure_and_values():
    bundle,inventory,_,c,targets,p=patch_fixture()
    p["decisions"][0].update(resolution="unsupported",span_ids=[],reason="The given source does not support the proposed method.")
    candidate,checks=apply_patch(c,EvidencePatch.model_validate(p),targets,bundle)
    assert candidate.model_dump()==c.model_dump() and checks["unresolved"]
    assert not validate(candidate,inventory,bundle)["valid"]


def test_worker_patch_retains_original_raw_and_reconstructs_final_proposal(tmp_path):
    bundle,inventory,raw,c,targets,p=patch_fixture()
    store=Store(tmp_path);bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=configuration(workflow="inventory_v3"))
    provider=SequenceProvider([inventory,raw,p]);outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="succeeded" and provider.calls==3
    packet=import_packet(store,job);verify_packet(packet)
    assert packet["receipt"]["selected_extraction_stage"]=="extraction_with_evidence_patch"
    assert json.loads(packet["raw_output"])==raw
    assert packet["receipt"]["evidence_patch"]["applied"]
    altered=deepcopy(packet["receipt"]);altered["extraction"]["results"][0]["quantity"]["value"]=93
    with pytest.raises(ValueError,match="evidence_patch_extraction_mismatch"):
        verify_applied_patch(altered,bundle,packet["raw_output"])


@pytest.mark.parametrize("change,connected",[("none",True),("page",False),("offset",False),("text",False)])
def test_repeated_context_is_equivalent_only_at_identical_original_coordinates(change,connected):
    bundle,inventory,raw=fixture()
    text=bundle.blocks[0].text
    locator=f"context-0:pdf_page:{2 if change=='page' else 1}:chars[{1 if change=='offset' else 0}:{len(text)+(1 if change=='offset' else 0)}]"
    bundle.blocks=make_blocks(bundle.documents[0].id,[
        (f"target:pdf_page:1:chars[0:{len(text)}]",text),
        (locator,text.replace("four-probe","four probe") if change=="text" else text)])
    inventory["processed_block_ids"]=raw["processed_block_ids"]=["B1","B2"]
    inventory["context_assertions"][0]["span_ids"]=["S2"]
    report=validate_coverage(CompactExtractionV3.model_validate(raw),Inventory.model_validate(inventory),bundle)
    assert ("context_field_evidence_disconnected" not in codes(report))==connected


def test_inventory_formula_disagreement_requires_review_without_rewriting_a_sample():
    bundle,inventory,raw=fixture()
    inventory["items"][0]["sample_raw"]="Re3Os3Mo0.5Hf0.5Nb3"
    raw["observations"][0]["sample"]["formula_raw"]="Re3.5Os3.5Mo0.5Hf0.5Nb3"
    compact=CompactExtractionV3.model_validate(raw)
    report=validate_coverage(compact,Inventory.model_validate(inventory),bundle)
    assert "inventory_subject_disagreement" in codes(report)
    assert compact.observations[0].sample.formula_raw==raw["observations"][0]["sample"]["formula_raw"]
    assert report["subject_disagreements"][0]["source_review_required"]
    inventory["items"][0]["sample_raw"]="Re 3.5Os3.5Mo0.5Hf0.5Nb3"
    assert "inventory_subject_disagreement" not in codes(validate_coverage(compact,Inventory.model_validate(inventory),bundle))


def test_claimed_results_without_observations_preserve_inventory_failure_diagnostics(tmp_path):
    bundle,inventory,raw=fixture();raw["observations"]=[]
    store=Store(tmp_path);bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=configuration(workflow="inventory_v3"))
    result=run_one(store,job_id=job,provider_override=SequenceProvider([inventory,raw]))
    assert result["state"]=="quarantined" and result["error_code"]=="output_contract_inconsistent"
    receipt=json.loads(next((tmp_path/"attempts"/job).glob("*/receipt.json")).read_text())
    assert "inventory_disposition_not_closed" in codes(receipt["inventory_coverage"])
    assert receipt["expansion_diagnostics"]
    assert json.loads(next((tmp_path/"attempts"/job).glob("*/output.json")).read_text())==raw
