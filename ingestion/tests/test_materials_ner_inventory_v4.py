"""Conditional bounds are not measured scan windows or point Tc labels."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner.contract import Quantity,digest,parse_extraction
from ingestion.materials_ner.evidence_patch import build_targets
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import import_packet,verify_packet
from ingestion.materials_ner.quantities import quantity_source_issues
from ingestion.materials_ner.sources import make_blocks,save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction,training_exclusions
from ingestion.materials_ner.wire_v4 import CompactExtractionV4,output_schema,validate_coverage
from ingestion.materials_ner.worker import configuration,run_one
from test_materials_ner_inventory_v3 import fixture as fixture_v3
from test_materials_ner_inventory_v2 import SequenceProvider,codes
from test_materials_ner_pipeline import quantity


def fixture():
    bundle,inventory,raw=fixture_v3()
    text=("SYNTHETIC FIXTURE. Sample A was nominal MgB2 in bulk form. "
          "Our own four-probe resistivity measurement found no superconducting transition. "
          "If Sample A is superconducting, its Tc is below 2.7 K.")
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",text)])
    raw["schema_version"]="materials-ner-compact/6"
    obs=raw["observations"][0]
    obs["state"]["conditions"]=[]
    obs["protocol"].update(criterion="unspecified",criterion_raw=None)
    obs["result"]["quantity_kind"]="non_detection"
    obs["result"]["quantity"]=quantity(None,"K",None,status="not_applicable",relation=None)
    obs["result"]["qualifiers"]=[
        {"kind":"conditional_existence","condition":"if_superconducting",
         "raw":"If Sample A is superconducting","tc_bound":quantity(None,"K","below 2.7 K",relation="lt",upper=2.7)},
        {"kind":"non_detection","target":"superconductivity","observable":"resistive_transition",
         "existence":"not_established","raw":"no superconducting transition",
         "window_status":"not_reported_in_supplied_source"}]
    for entity in ("sample","state","protocol","result"):
        for ref in obs[entity]["evidence"]:
            ref["fields"]=[f for f in ref["fields"] if f not in {"/conditions/0","/criterion","/criterion_raw"} and
                           not (entity=="result" and f=="/quantity")]
    obs["result"]["evidence"][0]["fields"].extend(["/qualifiers/0","/qualifiers/0/tc_bound","/qualifiers/1"])
    inventory["items"][0].update(value_raw=None,quantity_name_raw="Conditional superconductivity assertion")
    return bundle,inventory,raw


def test_v4_preserves_conditional_bound_without_manufacturing_a_measurement_window():
    bundle,inventory,raw=fixture();jsonschema.validate(raw,output_schema(bundle))
    compact=CompactExtractionV4.model_validate(raw);extraction=compact.expand(bundle)
    report=validate_extraction(extraction,bundle)
    assert report["valid"] and validate_coverage(compact,Inventory.model_validate(inventory),bundle)["valid"]
    assert extraction.results[0].quantity.status=="not_applicable"
    assert extraction.results[0].qualifiers[0].tc_bound.upper==2.7
    assert extraction.states[0].conditions==[]
    assert parse_extraction(extraction.model_dump()).model_dump()==extraction.model_dump()
    assessment=training_exclusions(extraction,bundle,report)
    assert not assessment["results"][0]["eligible"]
    assert "non_detection_measurement_window_unavailable" in assessment["results"][0]["reason_codes"]


@pytest.mark.parametrize("mutation,expected",[
    ("claimed_window","reported_detection_window_missing"),
    ("invented_extent","unreported_window_contains_reported_extent"),
    ("point_bound","conditional_tc_requires_bound_not_point"),
    ("wrong_bound","numeric_value_disagrees_with_raw"),
    ("missing_bound_evidence","field_evidence_missing"),
])
def test_window_missingness_and_conditional_numeric_semantics_are_enforced(mutation,expected):
    bundle,_,raw=fixture();obs=raw["observations"][0]
    if mutation=="claimed_window":obs["result"]["qualifiers"][1]["window_status"]="reported"
    if mutation=="invented_extent":
        obs["state"]["conditions"]=[{"kind":"temperature","role":"detection_window",
            "quantity":quantity(2.7,"K","2.7 K"),"window_position":"lower_limit",
            "orientation_raw":None,"basis_raw":"Unsupported inferred scan floor"}]
        obs["state"]["evidence"][0]["fields"].append("/conditions/0")
    if mutation=="point_bound":obs["result"]["qualifiers"][0]["tc_bound"]=quantity(2.7,"K","2.7 K")
    if mutation=="wrong_bound":obs["result"]["qualifiers"][0]["tc_bound"]["upper"]=7.2
    if mutation=="missing_bound_evidence":obs["result"]["evidence"][0]["fields"].remove("/qualifiers/0/tc_bound")
    assert expected in codes(validate_extraction(CompactExtractionV4.model_validate(raw).expand(bundle),bundle))
    if mutation=="point_bound":
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,output_schema(bundle))


def test_historical_v3_window_requirement_and_payload_shapes_remain_replayable():
    bundle,_,raw=fixture();old=deepcopy(raw);old["schema_version"]="materials-ner-compact/5"
    for qualifier in old["observations"][0]["result"]["qualifiers"]:
        qualifier.pop("tc_bound",None);qualifier.pop("window_status",None)
    from ingestion.materials_ner.wire_v3 import CompactExtractionV3
    extraction=CompactExtractionV3.model_validate(old).expand(bundle)
    assert "non_detection_window_missing" in codes(validate_extraction(extraction,bundle))
    assert "tc_bound" not in extraction.model_dump()["results"][0]["qualifiers"][0]


@pytest.mark.parametrize("raw,relation,key",[("below 2.7 K","lt","upper"),
    ("lower than 2.7 K","lt","upper"),("at most 2.7 K","le","upper"),
    ("above 2.7 K","gt","lower"),("at least 2.7 K","ge","lower")])
def test_literal_bound_words_are_parsed_without_rewriting_the_source(raw,relation,key):
    from ingestion.materials_ner.contract import Evidence
    q=Quantity.model_validate(quantity(None,"K",raw,relation=relation,**{key:2.7}))
    evidence=[Evidence(block_id="synthetic",quote="The reported limit is "+raw+".",field="/quantity")]
    assert quantity_source_issues("tc",q,evidence,"/quantity")==[]
    assert q.raw==raw


def test_v4_evidence_patch_and_real_packet_shape_reconstruct_without_scientific_approval(tmp_path):
    bundle,inventory,raw=fixture();obs=raw["observations"][0]
    obs["result"]["evidence"][0]["fields"].remove("/qualifiers/0/tc_bound")
    compact=CompactExtractionV4.model_validate(raw)
    validation=validate_extraction(compact.expand(bundle),bundle)
    targets=build_targets(compact,validation)
    patch={"schema_version":"materials-evidence-patch/1","work_id":bundle.work_id,
        "base_compact_sha256":digest(compact.model_dump()),"decisions":[
            {"target_id":t["id"],"resolution":"bound","span_ids":["S1"],"reason":None} for t in targets]}
    store=Store(tmp_path);bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=configuration(workflow="inventory_v4"))
    provider=SequenceProvider([inventory,raw,patch]);outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome["state"]=="succeeded" and provider.calls==3
    packet=import_packet(store,job);verify_packet(packet)
    assert packet["receipt"]["extraction"]["schema_version"]=="materials-ner/4"
    assert json.loads(packet["raw_output"])==raw and packet["receipt"]["evidence_patch"]["applied"]
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]


@pytest.mark.parametrize("unit,value",[("K",2.7),("mK",2700)])
def test_conditional_threshold_reused_as_a_reported_floor_requires_source_review(unit,value):
    bundle,_,raw=fixture();obs=raw["observations"][0]
    if unit=="mK":
        bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",
            bundle.blocks[0].text.replace("below 2.7 K", "below 2.7 K (2700 mK)"))])
    obs["result"]["qualifiers"][1]["window_status"]="reported"
    obs["state"]["conditions"]=[{"kind":"temperature","role":"detection_window",
        "quantity":quantity(value,unit,f"{value} {unit}"),"window_position":"lower_limit",
        "orientation_raw":None,"basis_raw":"Claimed measurement floor copied from a conditional threshold"}]
    obs["state"]["evidence"][0]["fields"].append("/conditions/0")
    extraction=CompactExtractionV4.model_validate(raw).expand(bundle)
    original=deepcopy(extraction.model_dump())
    report=validate_extraction(extraction,bundle)
    assert codes(report)=={"conditional_bound_window_requires_source_review"}
    assert extraction.model_dump()==original  # Triage never rewrites scientific data.


def test_a_separately_reported_scan_interval_is_not_a_copied_point_floor():
    bundle,_,raw=fixture();obs=raw["observations"][0]
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",bundle.blocks[0].text+
        " The temperature scan covered 2.7 to 8 K.")])
    obs["result"]["qualifiers"][1]["window_status"]="reported"
    obs["state"]["conditions"]=[{"kind":"temperature","role":"detection_window",
        "quantity":quantity(None,"K","2.7 to 8 K",relation="interval",lower=2.7,upper=8),
        "window_position":"interval","orientation_raw":None,"basis_raw":"Reported temperature scan"}]
    obs["state"]["evidence"][0]["fields"].append("/conditions/0")
    report=validate_extraction(CompactExtractionV4.model_validate(raw).expand(bundle),bundle)
    assert report["valid"],report["issues"]


def test_a_floor_with_separate_measurement_evidence_is_not_blocked_by_equal_bound_value():
    bundle,_,raw=fixture();obs=raw["observations"][0]
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",bundle.blocks[0].text),
        ("synthetic:2","The measurements extended down to 2.7 K.")])
    raw["processed_block_ids"]=["B1","B2"]
    obs["result"]["qualifiers"][1]["window_status"]="reported"
    obs["state"]["conditions"]=[{"kind":"temperature","role":"detection_window",
        "quantity":quantity(2.7,"K","2.7 K"),"window_position":"lower_limit",
        "orientation_raw":None,"basis_raw":"Reported measurement floor"}]
    obs["state"]["evidence"].append({"fields":["/conditions/0"],"span_ids":["S2"]})
    report=validate_extraction(CompactExtractionV4.model_validate(raw).expand(bundle),bundle)
    assert report["valid"],report["issues"]


def test_source_degree_glyph_is_a_unit_alias_without_rewriting_the_literal_quantity():
    from ingestion.materials_ner.contract import Evidence
    from ingestion.materials_ner.quantities import normalize
    q=Quantity.model_validate(quantity(680,"°C","680◦C"))
    evidence=[Evidence(block_id="synthetic",quote="Growth at 680◦C.",field="/quantity")]
    assert quantity_source_issues("temperature",q,evidence,"/quantity")==[]
    assert normalize("temperature",q)["normalized"]["value"]==953.15
    assert q.raw=="680◦C"
