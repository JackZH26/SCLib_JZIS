"""Coverage, scientific-shape and immutable import checks; synthetic, not Gold."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner.contract import canonical, parse_extraction
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import Inventory, output_schema as inventory_schema, validate_inventory
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v2 import CompactExtractionV2, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_pipeline import example, compact_fixture, quantity


def fixture():
    bundle,raw=example()
    bundle.work_id=raw["work_id"]="arxiv:synthetic-test"
    compact=compact_fixture(raw,bundle)
    compact.update(schema_version="materials-ner-compact/4",additional_items=[],unextracted_items=[])
    obs=compact["observations"][0]
    obs["inventory_item_ids"]=["I1"]
    obs["sample"]["additional_formula_assertions"]=[]
    obs["protocol"].update(method_class="resistivity",parameters=[])
    obs["protocol"]["evidence"][0]["fields"].append("/method_class")
    obs["result"]["qualifiers"]=[]
    inventory={"schema_version":"materials-source-inventory/1","work_id":bundle.work_id,
        "processed_block_ids":["B1"],"unread_block_ids":[],"limitations":[],"context_assertions":[],
        "items":[{"id":"I1","sample_raw":"Sample A","quantity_name_raw":"superconducting transition",
                  "value_raw":"39 K","source_span_ids":["S1"],"context_span_ids":[]}],
        "span_dispositions":[{"span_id":"S1","role":"result_assertions","item_ids":["I1"],"reason":None}]}
    return bundle,inventory,compact


def codes(report):return {i["code"] for i in report["issues"]}


def test_inventory_and_generation_schemas_preserve_closed_source_ids():
    bundle,inventory,compact=fixture()
    jsonschema.validate(inventory,inventory_schema(bundle))
    jsonschema.validate(compact,output_schema(bundle))
    assert validate_inventory(Inventory.model_validate(inventory),bundle)["valid"]
    inventory["items"][0]["source_span_ids"]=["S999"]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(inventory,inventory_schema(bundle))


@pytest.mark.parametrize("mutation,expected",[
    ("value","inventory_value_not_in_target_source"),
    ("block","inventory_block_coverage_mismatch"),
    ("span","inventory_target_disposition_mismatch"),
    ("item","inventory_item_without_target_disposition"),
])
def test_frozen_inventory_cannot_invent_values_or_hide_source_coverage(mutation,expected):
    bundle,inventory,_=fixture()
    if mutation=="value":inventory["items"][0]["value_raw"]="93 K"
    if mutation=="block":inventory["processed_block_ids"]=[]
    if mutation=="span":inventory["span_dispositions"]=[]
    if mutation=="item":inventory["span_dispositions"][0].update(role="no_relevant_result",item_ids=[],reason="Claimed empty")
    assert expected in codes(validate_inventory(Inventory.model_validate(inventory),bundle))


def test_context_value_is_not_an_inventory_target_even_when_another_target_is_selected():
    bundle,inventory,_=fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id,[("target:1","No numerical result in this span."),("context:1","Tc = 39 K.")])
    inventory["processed_block_ids"]=["B1","B2"]
    inventory["items"][0]["source_span_ids"]=["S1","S2"]
    assert "inventory_item_without_target" in codes(validate_inventory(Inventory.model_validate(inventory),bundle))


def test_silent_omission_cannot_be_hidden_by_completion_or_prose():
    bundle,inventory,compact=fixture()
    inventory["items"].append(dict(inventory["items"][0],id="I2"))
    inventory["span_dispositions"][0]["item_ids"].append("I2")
    compact["limitations"]=["All results retained."]
    report=validate_coverage(CompactExtractionV2.model_validate(compact),Inventory.model_validate(inventory),bundle)
    assert "inventory_disposition_not_closed" in codes(report)
    compact["unextracted_items"]=[{"item_id":"I2","reason":"unresolved","explanation":"Needs source review."}]
    report=validate_coverage(CompactExtractionV2.model_validate(compact),Inventory.model_validate(inventory),bundle)
    assert "inventory_disposition_not_closed" not in codes(report)
    assert "inventory_unextracted_results_require_review" in codes(report)


def test_second_read_can_add_source_supported_results_instead_of_obeying_incomplete_inventory():
    bundle,inventory,compact=fixture()
    compact["additional_items"]=[dict(inventory["items"][0],id="N1")]
    # In this synthetic example this is a repeated mention of the same result.
    compact["observations"][0]["inventory_item_ids"].append("N1")
    report=validate_coverage(CompactExtractionV2.model_validate(compact),Inventory.model_validate(inventory),bundle)
    assert report["valid"] and report["additional_items"]==1
    compact["additional_items"][0]["value_raw"]="93 K"
    assert "additional_inventory_source_invalid" in codes(validate_coverage(
        CompactExtractionV2.model_validate(compact),Inventory.model_validate(inventory),bundle))


def test_sparse_qualifiers_need_actual_source_evidence():
    bundle,_,compact=fixture()
    compact["observations"][0]["result"]["qualifiers"]=[{"kind":"transition_stage","stage":"secondary","raw":"secondary"}]
    extraction=CompactExtractionV2.model_validate(compact).expand(bundle)
    report=validate_extraction(extraction,bundle)
    assert {"field_evidence_missing","qualifier_raw_not_in_field_evidence"}<=codes(report)


def test_frequency_is_a_protocol_setting_and_has_its_own_dimension():
    bundle,_,compact=fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",bundle.blocks[0].text+" Probe frequency 1.5625 Hz.")])
    protocol=compact["observations"][0]["protocol"]
    protocol["parameters"]=[{"kind":"frequency","name_raw":"Probe frequency","quantity":quantity(1.5625,"Hz","1.5625 Hz")}]
    protocol["evidence"][0]["fields"].append("/parameters/0")
    report=validate_extraction(CompactExtractionV2.model_validate(compact).expand(bundle),bundle)
    assert report["valid"],report["issues"]
    assert report["normalized"]["/protocols/0/parameters/0/quantity"]["normalized"]["unit"]=="Hz"


def test_conditional_existence_cannot_enter_an_ordinary_tc_training_task():
    bundle,_,compact=fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",bundle.blocks[0].text+" if superconducting at all")])
    result=compact["observations"][0]["result"]
    result["qualifiers"]=[{"kind":"conditional_existence","condition":"if_superconducting","raw":"if superconducting at all"}]
    result["evidence"][0]["fields"].append("/qualifiers/0")
    extraction=CompactExtractionV2.model_validate(compact).expand(bundle)
    report=validate_extraction(extraction,bundle)
    assert "conditional_tc_requires_non_detection_review" in codes(report)
    assert "conditional_superconducting_existence" in training_exclusions(extraction,bundle,report)["results"][0]["reason_codes"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(compact,output_schema(bundle))


def test_fitted_system_tc_is_distinct_from_component_model_temperature():
    bundle,_,compact=fixture()
    obs=compact["observations"][0]
    obs["protocol"]["criterion"]="fit_parameter"
    obs["result"].update(origin="computed",qualifiers=[{"kind":"temperature_role","role":"system_transition","raw":"superconducting transition"}])
    obs["result"]["evidence"][0]["fields"].append("/qualifiers/0")
    report=validate_extraction(CompactExtractionV2.model_validate(compact).expand(bundle),bundle)
    assert "band_or_fit_temperature_requires_model_scale_review" not in codes(report)
    obs["result"]["qualifiers"][0]["role"]="component_model_parameter"
    assert "component_temperature_not_system_tc" in codes(validate_extraction(CompactExtractionV2.model_validate(compact).expand(bundle),bundle))


class SequenceProvider:
    def __init__(self,responses,fail_second=False):self.responses=responses;self.calls=0;self.fail_second=fail_second
    def extract(self,prompt,schema,config,directory):
        self.calls+=1
        if self.calls==2 and self.fail_second:raise ProviderFailure("synthetic_second_stage_failure",usage={"input_tokens":3})
        value=self.responses[self.calls-1]
        jsonschema.validate(value,schema)
        return ProviderResult(canonical(value),{"input_tokens":10,"output_tokens":2},"synthetic","gpt-6-luna",str(self.calls),.01)


def enqueue(tmp_path):
    bundle,inventory,compact=fixture()
    store=Store(tmp_path)
    bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=configuration(workflow="inventory_v2"))
    return store,job,inventory,compact


def test_two_stage_worker_retains_manifests_and_imports_v2_idempotently(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    provider=SequenceProvider([inventory,compact])
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="succeeded" and provider.calls==2
    packet=import_packet(store,job);verify_packet(packet)
    assert packet["receipt"]["inventory_coverage"]["emitted_items"]==1
    assert packet["receipt"]["extraction"]["schema_version"]=="materials-ner/2"
    assert packet["receipt"]["usage"]["input_tokens"]==20
    db=ProposalDatabase(tmp_path/"proposals")
    assert db.ingest(packet)["inserted"] and not db.ingest(packet)["inserted"]
    assert db.summary()["ml_training_eligible"] is False
    assert len(list(tmp_path.glob("attempts/*/*/inventory/output.json")))==1


def test_second_stage_failure_preserves_first_read_usage_and_output(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    outcome=run_one(store,job_id=job,provider_override=SequenceProvider([inventory,compact],True))
    assert outcome["state"]=="failed" and outcome["usage"]["input_tokens"]==13
    receipt=json.loads(next(tmp_path.glob("attempts/*/*/receipt.json")).read_text())
    assert receipt["inventory"]["items"] and "extraction" not in receipt


def test_inventory_repair_is_bounded_source_checked_and_preserves_initial_failure(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    invalid=deepcopy(inventory)
    invalid["items"][0]["value_raw"]="93 K"
    provider=SequenceProvider([invalid,inventory,compact])
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="succeeded" and provider.calls==3
    receipt_path=next(tmp_path.glob("attempts/*/*/receipt.json"))
    receipt=json.loads(receipt_path.read_text())
    assert not receipt["inventory_reads"][0]["validation"]["valid"]
    assert receipt["inventory_reads"][1]["validation"]["valid"]
    assert json.loads(receipt_path.with_name("inventory").joinpath("output.json").read_text())==invalid
    assert json.loads(receipt_path.with_name("inventory-repair").joinpath("output.json").read_text())==inventory
    assert receipt["usage"]["input_tokens"]==30


def test_failed_inventory_repair_does_not_call_extraction_or_clear_failure(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    inventory["items"][0]["value_raw"]="93 K"
    provider=SequenceProvider([inventory,inventory,compact])
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="quarantined" and provider.calls==2
    assert outcome["error_code"]=="source_inventory_contract_invalid"
    receipt=json.loads(next(tmp_path.glob("attempts/*/*/receipt.json")).read_text())
    assert "extraction" not in receipt and not receipt["inventory_validation"]["valid"]


def test_repair_does_not_accept_context_as_target_evidence(tmp_path):
    bundle,inventory,compact=fixture()
    bundle.blocks=make_blocks(bundle.documents[0].id,[("target:1","No result in this target."),("context:1","Tc = 39 K.")])
    inventory["processed_block_ids"]=["B1","B2"]
    invalid=deepcopy(inventory)
    inventory["items"][0]["context_span_ids"]=["S2"]
    store=Store(tmp_path)
    bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=configuration(workflow="inventory_v2"))
    provider=SequenceProvider([invalid,inventory,compact])
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="quarantined" and provider.calls==2
    receipt=json.loads(next(tmp_path.glob("attempts/*/*/receipt.json")).read_text())
    assert "inventory_value_not_in_target_source" in codes(receipt["inventory_validation"])


def test_extraction_repair_revalidates_bindings_and_keeps_both_raw_reads(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    invalid=deepcopy(compact)
    invalid["observations"][0]["result"]["evidence"][0]["fields"].remove("/sample_id")
    provider=SequenceProvider([inventory,invalid,compact])
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="succeeded" and provider.calls==3
    p=next(tmp_path.glob("attempts/*/*/receipt.json"));receipt=json.loads(p.read_text())
    assert receipt["selected_extraction_stage"]=="extraction_repair"
    assert not receipt["extraction_reads"][0]["valid"] and receipt["extraction_reads"][1]["valid"]
    assert json.loads(p.with_name("extraction-initial").joinpath("output.json").read_text())==invalid
    assert json.loads(p.with_name("extraction-repair").joinpath("output.json").read_text())==compact
    assert json.loads(p.with_name("output.json").read_text())==compact
    verify_packet(import_packet(store,job))


def test_extraction_repair_cannot_loop_or_erase_unfixed_contract_issues(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    compact["observations"][0]["result"]["evidence"][0]["fields"].remove("/sample_id")
    provider=SequenceProvider([inventory,compact,compact])
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="quarantined" and provider.calls==3
    receipt=json.loads(next(tmp_path.glob("attempts/*/*/receipt.json")).read_text())
    assert "field_evidence_missing" in codes(receipt["validation"])
    assert all(not read["valid"] for read in receipt["extraction_reads"])


def test_repair_cannot_drop_an_asserted_method_to_make_validation_pass(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    invalid=deepcopy(compact)
    invalid["observations"][0]["protocol"]["evidence"][0]["fields"].remove("/method")
    destructive=deepcopy(invalid)
    destructive["observations"][0]["protocol"]["method"]=None
    provider=SequenceProvider([inventory,invalid,destructive])
    outcome=run_one(store,job_id=job,provider_override=provider)
    p=next(tmp_path.glob("attempts/*/*/receipt.json"));receipt=json.loads(p.read_text())
    assert outcome["state"]=="quarantined" and provider.calls==3
    assert receipt["selected_extraction_stage"]=="extraction"
    assert not receipt["extraction_repair_selection"]["admitted"]
    assert "scientific_payload_changed_requires_source_review" in receipt["extraction_repair_selection"]["reason_codes"]
    assert json.loads(p.with_name("output.json").read_text())==invalid
    assert json.loads(p.with_name("extraction-repair").joinpath("output.json").read_text())==destructive
    verify_packet(import_packet(store,job))


def test_repair_cannot_replace_one_missing_evidence_field_with_another(tmp_path):
    store,job,inventory,compact=enqueue(tmp_path)
    invalid=deepcopy(compact)
    invalid["observations"][0]["result"]["evidence"][0]["fields"].remove("/sample_id")
    regressed=deepcopy(compact)
    regressed["observations"][0]["result"]["evidence"][0]["fields"].remove("/origin")
    outcome=run_one(store,job_id=job,provider_override=SequenceProvider([inventory,invalid,regressed]))
    receipt=json.loads(next(tmp_path.glob("attempts/*/*/receipt.json")).read_text())
    assert outcome["state"]=="quarantined"
    assert receipt["selected_extraction_stage"]=="extraction"
    assert receipt["extraction_repair_selection"]["reason_codes"]==["new_validation_issues"]


def test_old_receipts_round_trip_without_adding_v2_defaults():
    _,raw=example()
    # The legacy class historically supplies quantity_name_raw; all other old
    # field structure and the schema version must be preserved verbatim.
    assert parse_extraction(raw).model_dump()==raw
