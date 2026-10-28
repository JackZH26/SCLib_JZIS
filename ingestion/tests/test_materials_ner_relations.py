"""Source ownership and method-specific geometry: synthetic engineering tests.

Inspired by the nickelate source review. These fixtures are not scientific Gold.
"""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import Quantity, digest, parse_extraction
from ingestion.materials_ner.evidence_patch import verify_applied_patch
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import import_packet, verify_packet, review_rows, ProposalDatabase
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.validation_v6 import same_quantity
from ingestion.materials_ner.wire_v8 import RelationalExtraction, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_native import fixture as native_fixture
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_pipeline import quantity


def fixture():
    bundle, inventory, raw = native_fixture()
    text = (bundle.blocks[0].text + " MgO inclusions are components of Sample A. "
            "X-ray reflectivity and TEM each measured Sample A total thickness as 8 nm.")
    bundle.blocks = make_blocks(bundle.documents[0].id, [("synthetic:1", text)])
    raw.update(schema_version="materials-ner-shared/4", sample_relations=[], condition_supports=[])
    sample = raw["samples"][0]
    sample["evidence"][0]["fields"] += ["/label", "/form_raw", "/target_kind"]
    component = deepcopy(sample)
    component.update(id="component-A", label="MgO inclusions", formula_raw="MgO", target_kind="component",
                     form_raw=None, composition_basis="unresolved")
    component["evidence"][0]["fields"] = ["/label", "/formula_raw", "/target_kind"]
    raw["samples"].append(component)
    raw["sample_relations"].append({"id": "inclusion", "from_sample_id": component["id"], "to_sample_id": sample["id"],
        "relation": "component_of", "relation_raw": "MgO inclusions are components of Sample A.",
        "evidence": [{"span_ids": ["S1"], "fields": ["/from_sample_id", "/to_sample_id", "/relation", "/relation_raw"]}]})
    state = raw["states"][0]
    state["conditions"] = [{"id": "geometry", "kind": "thickness", "role": "sample_geometry",
        "quantity": quantity(8, "nm", "8 nm"), "orientation_raw": None, "basis_raw": None, "window_position": None}]
    state["evidence"][0]["fields"].append("/conditions/0")
    for number, method in enumerate(("X-ray reflectivity", "TEM"), 3):
        procedure = deepcopy(raw["protocols"][0])
        procedure.update(id=method, method=method, method_class="other", observable="total thickness")
        procedure["context_uses"] = [{"state_id": state["id"], "condition_id": "geometry"}]
        procedure["evidence"][0]["fields"].append("/context_uses/0")
        raw["protocols"].append(procedure)
        observation = deepcopy(raw["observations"][0])
        observation.update(id=f"O{number}", protocol_id=method, inventory_item_ids=[f"I{number}"])
        observation["result"].update(quantity_kind="thickness", quantity=quantity(8,"nm","8 nm"))
        observation["definition"].update(criterion="not_applicable", criterion_raw=None, evidence=[])
        raw["observations"].append(observation)
        inventory["items"].append(dict(inventory["items"][0], id=f"I{number}", quantity_name_raw="total thickness", value_raw="8 nm"))
        inventory["span_dispositions"][0]["item_ids"].append(f"I{number}")
        raw["condition_supports"].append({"id": f"support-{number}", "result_id": observation["id"],
            "state_id": state["id"], "condition_id": "geometry", "relation": "measures",
            "relation_raw": "X-ray reflectivity and TEM each measured Sample A total thickness as 8 nm.",
            "evidence": [{"span_ids": ["S1"], "fields": ["/result_id", "/state_id", "/condition_id", "/relation", "/relation_raw"]}]})
    return bundle, inventory, raw


def checked(wire, inventory, bundle):
    report = validate_extraction(wire.expand(bundle), bundle)
    report["issues"].extend(validate_coverage(wire, Inventory.model_validate(inventory), bundle)["issues"])
    report["valid"] = not report["issues"]
    return report


def test_graph_preserves_component_scope_and_equal_method_specific_measurements():
    bundle, inventory, raw = fixture()
    schema = output_schema(bundle, Inventory.model_validate(inventory))
    jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(raw,schema)
    wire = RelationalExtraction.model_validate(raw); extraction=wire.expand(bundle)
    assert checked(wire,inventory,bundle)["valid"]
    assert len(extraction.samples)==2 and len(extraction.states)==1
    assert all(r.sample_id=="sample-A" for r in extraction.results)
    assert [r.quantity.value for r in extraction.results if r.quantity_kind=="thickness"]==[8,8]
    assert len({r.protocol_id for r in extraction.results if r.quantity_kind=="thickness"})==2
    assert parse_extraction(extraction.model_dump()).model_dump()==extraction.model_dump()
    assert wire.model_dump()==raw
    gate=training_exclusions(extraction,bundle,checked(wire,inventory,bundle))
    assert all(not r["eligible"] for r in gate["results"])


@pytest.mark.parametrize("mutation",["missing_sample","self","duplicate_edge","cycle","duplicate_condition",
    "missing_condition","cross_state","duplicate_support","bad_context_use"])
def test_invalid_graph_references_are_rejected_before_storage(mutation):
    bundle,_,raw=fixture()
    if mutation=="missing_sample": raw["sample_relations"][0]["from_sample_id"]="absent"
    if mutation=="self": raw["sample_relations"][0]["from_sample_id"]="sample-A"
    if mutation=="duplicate_edge": raw["sample_relations"].append(dict(raw["sample_relations"][0],id="duplicate"))
    if mutation=="cycle": raw["sample_relations"].append(dict(raw["sample_relations"][0],id="cycle",from_sample_id="sample-A",to_sample_id="component-A"))
    if mutation=="duplicate_condition": raw["states"][0]["conditions"]*=2
    if mutation=="missing_condition": raw["condition_supports"][0]["condition_id"]="absent"
    if mutation=="cross_state":
        raw["states"].append(dict(raw["states"][0],id="state-B"))
        raw["condition_supports"][0]["state_id"]="state-B"
    if mutation=="duplicate_support": raw["condition_supports"].append(dict(raw["condition_supports"][0],id="duplicate"))
    if mutation=="bad_context_use": raw["protocols"][1]["context_uses"][0]["condition_id"]="absent"
    with pytest.raises(ValidationError): RelationalExtraction.model_validate(raw).expand(bundle)


def test_stable_condition_reference_survives_reordering():
    bundle,_,raw=fixture()
    raw["states"][0]["conditions"].append(dict(raw["states"][0]["conditions"][0],id="separate-assertion"))
    before=RelationalExtraction.model_validate(raw).expand(bundle)
    raw["states"][0]["conditions"].reverse()
    after=RelationalExtraction.model_validate(raw).expand(bundle)
    assert after.condition_supports==before.condition_supports
    assert after.protocols==before.protocols
    assert next(c for c in after.states[0].conditions if c.id==after.condition_supports[0].condition_id).id=="geometry"


@pytest.mark.parametrize("mutation,code",[
    ("fitted_layer","condition_support_quantity_kind_mismatch"),
    ("approximate","condition_support_quantity_mismatch"),
    ("different_value","condition_support_quantity_mismatch"),
    ("unknown_method","condition_measurement_method_unresolved"),
    ("theory","condition_measurement_origin_unresolved"),
    ("relation_quote","relation_raw_not_in_field_evidence"),
    ("missing_endpoint_evidence","field_evidence_missing")])
def test_scientific_disagreements_are_retained_and_quarantined(mutation,code):
    bundle,inventory,raw=fixture()
    if mutation=="fitted_layer": raw["observations"][2]["result"]["quantity_kind"]="superconducting_layer_thickness"
    if mutation=="approximate": raw["observations"][2]["result"]["quantity"]["approximate"]=True
    if mutation=="different_value": raw["observations"][2]["result"]["quantity"]["value"]=7
    if mutation=="unknown_method": raw["protocols"][1]["method"]=None
    if mutation=="theory": raw["observations"][2]["result"]["origin"]="computed"
    if mutation=="relation_quote": raw["condition_supports"][0]["relation_raw"]="invented text"
    if mutation=="missing_endpoint_evidence": raw["condition_supports"][0]["evidence"][0]["fields"].remove("/condition_id")
    wire=RelationalExtraction.model_validate(raw); report=checked(wire,inventory,bundle)
    assert code in {i["code"] for i in report["issues"]}
    rows=review_rows(wire.expand(bundle),report)
    assert len(rows["results"])==4 and len(rows["condition_supports"])==2
    assert all(r["review_status"]=="quarantined" for r in rows["results"])


def test_component_evidence_failure_propagates_to_parent_results_without_inheriting_them():
    bundle,inventory,raw=fixture()
    raw["samples"][1]["evidence"][0]["fields"].remove("/formula_raw")
    wire=RelationalExtraction.model_validate(raw)
    rows=review_rows(wire.expand(bundle),checked(wire,inventory,bundle))
    assert all(r["review_status"]=="quarantined" for r in rows["results"])
    assert all(r["payload"]["sample_id"]=="sample-A" for r in rows["results"])
    assert "sample_relation_has_validation_issues" in rows["samples"][0]["issues"]


def test_worker_import_idempotence_fk_backup_and_raw_reconstruction(tmp_path):
    bundle,inventory,raw=fixture(); store=Store(tmp_path)
    bundle_hash,_=save_bundle(tmp_path,bundle)
    config=configuration(workflow="inventory_v8")
    assert config["max_evidence_patches"]==0
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=config)
    provider=SequenceProvider([inventory,raw])
    assert run_one(store,job_id=job,provider_override=provider)["state"]=="succeeded"
    assert provider.calls==2
    packet=import_packet(store,job); verify_packet(packet)
    assert packet["schema"]=="materials-ner-proposals/2"
    db=ProposalDatabase(tmp_path/"private")
    assert db.ingest(packet)["inserted"] and not db.ingest(packet)["inserted"]
    assert db.summary()["tables"]["sample_relations"]==1
    assert db.summary()["tables"]["conditions"]==1 and db.summary()["tables"]["condition_supports"]==2
    assert not packet["scientific_acceptance"] and not packet["ml_training_eligible"]
    with db.connect() as conn:
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        with sqlite3.connect(tmp_path/"restored.sqlite") as restored:
            conn.backup(restored)
            assert json.loads(restored.execute("SELECT payload FROM runs").fetchone()[0])==packet
            assert restored.execute("SELECT count(*) FROM condition_supports").fetchone()[0]==2
    with pytest.raises(sqlite3.IntegrityError), db.connect() as conn:
        conn.execute("UPDATE condition_supports SET condition_id='missing'")
    changed=deepcopy(packet["receipt"]); changed["extraction"]["sample_relations"][0]["relation_raw"]="fabricated"
    with pytest.raises(ValueError,match="shared_extraction_reconstruction_mismatch"):
        verify_applied_patch(changed,bundle,packet["raw_output"])
    tampered=deepcopy(packet); tampered["rows"]["condition_supports"]=[]
    tampered["packet_hash"]=digest({k:v for k,v in tampered.items() if k!="packet_hash"})
    with pytest.raises(ValueError,match="proposal row derivation mismatch"): verify_packet(tampered)


def test_legacy_worker_packet_keeps_original_contract_and_empty_relation_tables(tmp_path):
    bundle,inventory,raw=native_fixture(); store=Store(tmp_path)
    bundle_hash,_=save_bundle(tmp_path,bundle)
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=configuration(workflow="inventory_v7"))
    assert run_one(store,job_id=job,provider_override=SequenceProvider([inventory,raw]))["state"]=="succeeded"
    packet=import_packet(store,job); verify_packet(packet)
    assert packet["schema"]=="materials-ner-proposals/1" and "sample_relations" not in packet["rows"]
    db=ProposalDatabase(tmp_path/"private"); db.ingest(packet)
    assert all(db.summary()["tables"][k]==0 for k in ("conditions","sample_relations","condition_supports"))


@pytest.mark.parametrize("mutation,expected",[("units",True),("interval",True),("bound",False),
    ("uncertainty_level",False),("uncertainty_value",False),("unreported",False)])
def test_condition_support_comparison_retains_full_numeric_semantics(mutation,expected):
    a=quantity(8,"nm","8 nm"); b=deepcopy(a)
    if mutation=="units": b.update(value=80,unit="Å",raw="80 Å")
    if mutation in {"interval","bound"}:
        a.update(relation="interval",value=None,lower=7,upper=8,raw="7–8 nm")
        b=deepcopy(a)
        if mutation=="bound": b.update(relation="le",lower=None,raw="≤8 nm")
    if mutation.startswith("uncertainty_"):
        a["uncertainty"]={"kind":"confidence_interval","minus":0.1,"plus":0.1,"level":0.95,"raw":"±0.1 nm"}
        b=deepcopy(a)
        b["uncertainty"].update({"level":0.9} if mutation=="uncertainty_level" else {"plus":0.2})
    if mutation=="unreported": b={"status":"not_reported"}
    assert same_quantity("thickness",Quantity.model_validate(a),Quantity.model_validate(b)) is expected


def test_relation_failure_does_not_quarantine_an_unrelated_specimen():
    bundle,inventory,raw=fixture()
    raw["samples"].append(dict(raw["samples"][0],id="sample-B"))
    raw["states"].append(dict(raw["states"][0],id="state-B",sample_id="sample-B",conditions=[],
        evidence=[{"span_ids":["S1"],"fields":["/sample_id"]}]))
    other=deepcopy(raw["observations"][0]); other.update(id="other",sample_id="sample-B",state_id="state-B")
    raw["observations"].append(other)
    raw["condition_supports"][0]["relation_raw"]="invented"
    wire=RelationalExtraction.model_validate(raw)
    # No inventory coverage check here: the fixture tests graph error scope only.
    rows=review_rows(wire.expand(bundle),validate_extraction(wire.expand(bundle),bundle))
    assert rows["results"][-1]["review_status"]=="pending_review"
    assert all(r["review_status"]=="quarantined" for r in rows["results"][:-1])


def test_missing_measurement_support_is_visible_without_inventing_an_edge():
    bundle,inventory,raw=fixture();raw["condition_supports"].pop(0)
    wire=RelationalExtraction.model_validate(raw);extraction=wire.expand(bundle)
    report=checked(wire,inventory,bundle)
    assert {i["code"] for i in report["issues"]}=={"geometry_condition_support_requires_review"}
    rows=review_rows(extraction,report)
    assert rows["results"][2]["review_status"]=="quarantined"
    assert rows["results"][0]["review_status"]=="pending_review"
    assert len(extraction.condition_supports)==1
