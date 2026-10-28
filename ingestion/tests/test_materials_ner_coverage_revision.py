"""Newly discovered assertions survive as explicit source-owned review holds."""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest

from ingestion.materials_ner import coverage_revision as contract
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import ProposalDatabase,verify_packet
from ingestion.materials_ner.scoped_review import resolve_parent,configuration as old_configuration
from test_materials_ner_scoped_revision import fixture as parent_fixture,execute


def fixture(tmp_path):
    store,bundle,parent,request,response=parent_fixture(tmp_path)
    graph,_=resolve_parent(parent,bundle)
    request['issues']=[{'id':'source-discovery','concern':'Account for the literal fit-domain statement without inventing a result.',
        'targets':[{'entity':'document','entity_id':bundle.work_id}],'span_ids':['S1']}]
    source_item={'id':'U1','sample_raw':graph.samples[0].formula_raw,'quantity_name_raw':'fit-domain statement',
        'value_raw':'20 to 70 K','source_span_ids':['S1'],'context_span_ids':[]}
    response.update(schema_version=contract.VERSION,request_sha256=digest(request),condition_changes=[],
        edits=[{'entity':'additional_item','action':'add','value':source_item,
                'reason':'Retain the newly considered source statement.','span_ids':['S1']},
               {'entity':'unextracted_item','action':'add','value':{'item_id':'U1','reason':'not_a_result',
                'explanation':'This is a fit domain, not a fitted value; retain the explicit source decision for review.'},
                'reason':'Do not invent a result to account for a source phrase.','span_ids':['S1']}],
        dispositions=[{'issue_id':'source-discovery','status':'revised','reason':'Source item and exclusion retained for review.',
            'span_ids':['S1'],'entities':[{'entity':'document','entity_id':bundle.work_id},
                {'entity':'additional_item','entity_id':'U1'},{'entity':'unextracted_item','entity_id':'U1'}]}])
    return store,bundle,parent,request,response


def test_source_assertion_and_explicit_exclusion_roundtrip_without_new_result(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    schema=contract.output_schema(bundle,Inventory.model_validate(parent['receipt']['inventory']),parent,review_request=request)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(response,schema)
    outcome,packet=execute(store,bundle,parent,request,response,mode='coverage_review')
    assert outcome['state']=='quarantined'
    assert packet['receipt']['extraction']['results']==parent['receipt']['extraction']['results']
    assert any(i['code']=='inventory_unextracted_results_require_review' for i in packet['receipt']['validation']['issues'])
    assert len(packet['receipt']['revision_audit']['source_item_changes'])==2
    next_parent={k:packet[k] for k in ['run_id','receipt','raw_output']};graph,_=resolve_parent(next_parent,bundle)
    assert graph.additional_items[0].value_raw=='20 to 70 K' and graph.unextracted_items[0].item_id=='U1'
    assert graph.states==resolve_parent(parent,bundle)[0].states
    with pytest.raises(ValueError,match='condition_revision_downgrade_forbidden'):
        old_configuration(next_parent,review_request=dict(request,parent_run_id=next_parent['run_id']))
    database=ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as db,sqlite3.connect(tmp_path/'backup.sqlite3') as backup:
        db.backup(backup);assert not backup.execute('PRAGMA foreign_key_check').fetchall()
        restored=json.loads(backup.execute('SELECT payload FROM runs').fetchone()[0])
        assert restored==packet;verify_packet(restored)
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_unextracted_item_cannot_be_added_without_a_source_item(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    response['edits']=response['edits'][1:]
    outcome,packet=execute(store,bundle,parent,request,response,mode='coverage_review')
    assert outcome['state']=='quarantined' and 'extraction' not in packet['receipt']
    assert packet['receipt']['revision_error_detail']=='coverage_revision_unextracted_source_disconnected'


def test_new_review_hold_cannot_be_resolved_by_an_unrelated_old_observation(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    _,packet=execute(store,bundle,parent,request,response,mode='coverage_review')
    parent={k:packet[k] for k in ['run_id','receipt','raw_output']};graph,_=resolve_parent(parent,bundle)
    request['parent_run_id']=parent['run_id']
    response.update(parent_run_id=parent['run_id'],request_sha256=digest(request),base_graph_sha256=digest(graph.model_dump()),
        edits=[],resolved_unextracted_items=[{'item_id':'U1','observation_ids':[graph.observations[0].id],
        'reason':'Invalid fixture: old observation is unrelated.','span_ids':['S1']}])
    outcome,packet=execute(store,bundle,parent,request,response,mode='coverage_review')
    assert outcome['state']=='quarantined' and 'extraction' not in packet['receipt']


def test_revision_request_and_item_audit_are_reconstructed_not_trusted(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    _,packet=execute(store,bundle,parent,request,response,mode='coverage_review')
    receipt=deepcopy(packet['receipt']);receipt['revision_audit']['source_item_changes']=[]
    with pytest.raises(ValueError,match='coverage_receipt_reconstruction_mismatch'):
        contract.verify_receipt(receipt,bundle,packet['raw_output'])
