"""Scoped revisions retain roles, original ancestry and every pending review issue."""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest

from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.native_revision import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.relational_revision import resolve_parent as legacy_parent
from ingestion.materials_ner.relational_review import pending_review_issues
from ingestion.materials_ner.scoped_review import (
    VERSION, resolve_parent, validate_request, output_schema, verify_receipt)
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration as initial_config, run_one as initial_run
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_scoped_conditions import fixture as source_fixture


def fixture(tmp_path):
    bundle, inventory, raw = source_fixture()
    store = Store(tmp_path)
    bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=initial_config(workflow='inventory_v9'))
    initial_run(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    packet = import_packet(store, job)
    parent = {k:packet[k] for k in ('run_id','receipt','raw_output')}
    graph, _ = resolve_parent(parent, bundle)
    raw = graph.model_dump()
    state = deepcopy(raw['states'][0])
    state['conditions'][1]['basis_raw'] = '10 to 30 GPa'
    request = {'schema_version':'materials-source-review-request/1', 'work_id':bundle.work_id,
        'parent_run_id':parent['run_id'], 'bundle_sha256':bundle_hash, 'author_kind':'assistant',
        'issues':[{'id':'phase-scope', 'concern':'Check the source scope of the pressure domain.',
            'targets':[{'entity':'state','entity_id':state['id']}], 'span_ids':['S1']}]}
    response = {'schema_version':VERSION, 'work_id':bundle.work_id, 'parent_run_id':parent['run_id'],
        'base_graph_sha256':digest(raw), 'request_sha256':digest(request),
        'edits':[{'entity':'state','action':'replace','value':state,'reason':'Retain the literal range basis.','span_ids':['S1']}],
        'resolved_unextracted_items':[], 'document_edit':None,
        'dispositions':[{'issue_id':'phase-scope','status':'revised','reason':'Retain the stated phase range with study scope.',
                         'span_ids':['S1'],'entities':request['issues'][0]['targets']}]}
    return store,bundle,parent,request,response


def execute(store,bundle,parent,request,response,mode='scoped_review'):
    config = configuration(parent,mode=mode,review_request=request)
    job = store.enqueue(work_id=bundle.work_id,bundle_hash=parent['receipt']['bundle_sha256'],config=config,max_attempts=1)
    provider = SequenceProvider([response])
    outcome = run_one(store,job,parent,bundle,mode=mode,provider_override=provider)
    packet = import_packet(store,job);verify_packet(packet)
    assert provider.calls == 1
    return outcome,packet


def test_scoped_review_schema_and_immutable_archive_keep_roles_and_unknown_pressure(tmp_path):
    store,bundle,parent,request,response = fixture(tmp_path)
    original = deepcopy(parent)
    schema = output_schema(bundle,Inventory.model_validate(parent['receipt']['inventory']),parent,review_request=request)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(response,schema)
    with pytest.raises(ValueError,match='unsupported_relation_revision_parent'):legacy_parent(parent,bundle)
    outcome,packet = execute(store,bundle,parent,request,response)
    assert outcome['state'] == 'succeeded' and parent == original
    graph,_ = resolve_parent({k:packet[k] for k in ('run_id','receipt','raw_output')},bundle)
    assert [c.role for c in graph.states[0].conditions[1:]] == ['study_extent','fit_window']
    assert all('measurement_pressure_unknown' in r['reason_codes'] for r in packet['receipt']['training_assessment']['results'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    database=ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection,sqlite3.connect(tmp_path/'restored.sqlite3') as restored:
        connection.backup(restored)
        assert not restored.execute('PRAGMA foreign_key_check').fetchall()
        assert json.loads(restored.execute('SELECT payload FROM runs').fetchone()[0]) == packet


@pytest.mark.parametrize('mutation',['parent','bundle','target','span','duplicate_issue'])
def test_scoped_review_request_is_bound_to_exact_parent_and_original_source(tmp_path,mutation):
    _,bundle,parent,request,_=fixture(tmp_path)
    if mutation=='parent':request['parent_run_id']='0'*64
    if mutation=='bundle':request['bundle_sha256']='0'*64
    if mutation=='target':request['issues'][0]['targets'][0]['entity_id']='absent'
    if mutation=='span':request['issues'][0]['span_ids']=['S999']
    if mutation=='duplicate_issue':request['issues']*=2
    with pytest.raises(ValueError):validate_request(request,parent,bundle)


@pytest.mark.parametrize('mutation',['request','graph','audit','omitted_hold'])
def test_reconstruction_detects_tampering_and_removed_holds(tmp_path,mutation):
    store,bundle,parent,request,response=fixture(tmp_path)
    response['dispositions'][0]['status']='unresolved'
    _,packet=execute(store,bundle,parent,request,response)
    receipt=deepcopy(packet['receipt'])
    if mutation=='request':receipt['review_request']['issues'][0]['concern']='Different review'
    if mutation=='graph':receipt['extraction']['states'][0]['conditions'][1]['role']='measurement'
    if mutation=='audit':receipt['revision_audit']['changes']=[]
    if mutation=='omitted_hold':receipt['validation']['issues']=[]
    with pytest.raises(ValueError):verify_receipt(receipt,bundle,packet['raw_output'])


def test_failed_issue_accounting_carries_all_requests_into_next_revision(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    response['dispositions'][0]['status']='unchanged_supported'
    outcome,packet=execute(store,bundle,parent,request,response)
    assert outcome['state']=='quarantined'
    next_parent={k:packet[k] for k in ('run_id','receipt','raw_output')}
    assert pending_review_issues(next_parent)==request['issues']
    next_request=deepcopy(request);next_request['parent_run_id']=packet['run_id']
    next_request['issues'][0]['concern']='An easier replacement'
    with pytest.raises(ValueError,match='drops_or_rewrites_unresolved'):
        validate_request(next_request,next_parent,bundle)


def test_scoped_source_selection_then_review_reconstructs_exact_ancestry(tmp_path):
    from ingestion.materials_ner import source_field_scoped as fields
    store,bundle,parent,request,response=fixture(tmp_path)
    _,first=execute(store,bundle,parent,request,response)
    parent2={k:first[k] for k in ('run_id','receipt','raw_output')};graph,_=resolve_parent(parent2,bundle)
    field_request=dict(deepcopy(request),schema_version='materials-source-field-request/1',parent_run_id=first['run_id'],
        fields=[{'id':'range-basis','issue_id':'phase-scope','entity':'state','entity_id':graph.states[0].id,
            'field':'/conditions/1/basis_raw','expected_value_sha256':digest('10 to 30 GPa'),
            'kind':'raw_literal','allow_absent':False}])
    field_response={'schema_version':fields.VERSION,'work_id':bundle.work_id,'parent_run_id':first['run_id'],
        'base_graph_sha256':digest(graph.model_dump()),'request_sha256':digest(field_request),
        'selections':[{'target_id':'range-basis','action':'copy','span_ids':['S1'],'exact_text':'10 to 30 GPa',
                       'occurrence':None,'reason':'Select the exact pressure range.'}]}
    schema=fields.output_schema(bundle,Inventory.model_validate(parent2['receipt']['inventory']),parent2,review_request=field_request)
    jsonschema.validate(field_response,schema)
    outcome,second=execute(store,bundle,parent2,field_request,field_response,mode='scoped_fields')
    assert outcome['state']=='quarantined'
    parent3={k:second[k] for k in ('run_id','receipt','raw_output')};graph3,_=resolve_parent(parent3,bundle)
    assert graph3.states[0].conditions[1].role=='study_extent'
    assert pending_review_issues(parent3)==request['issues']
    next_request=dict(deepcopy(request),parent_run_id=second['run_id'])
    response.update(parent_run_id=second['run_id'],base_graph_sha256=digest(graph3.model_dump()),
                    request_sha256=digest(next_request),edits=[])
    response['dispositions'][0]['status']='unchanged_supported'
    outcome,third=execute(store,bundle,parent3,next_request,response)
    assert outcome['state']=='succeeded'
    assert not third['receipt']['revision_audit']['independent_review']
    assert third['receipt']['extraction']==second['receipt']['extraction']
    resolved,_=resolve_parent({k:third[k] for k in ('run_id','receipt','raw_output')},bundle)
    assert resolved.model_dump()==graph3.model_dump()
