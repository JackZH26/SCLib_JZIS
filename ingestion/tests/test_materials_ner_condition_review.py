"""Nested changes cannot erase retained conditions as an incidental state edit."""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest

from ingestion.materials_ner import condition_review as contract
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import ProposalDatabase, verify_packet
from ingestion.materials_ner.scoped_review import resolve_parent
from test_materials_ner_scoped_revision import fixture as old_fixture, execute


def fixture(tmp_path):
    store, bundle, parent, request, response = old_fixture(tmp_path)
    graph, _ = resolve_parent(parent, bundle)
    old = graph.states[0].conditions[1]
    response.update(schema_version=contract.VERSION, condition_changes=[{
        'state_id': graph.states[0].id, 'condition_id': old.id, 'action': 'replace',
        'before_sha256': digest(old.model_dump()), 'reason': 'Retain the exact pressure range basis.',
        'span_ids': ['S1']}])
    return store, bundle, parent, request, response


def test_exact_condition_change_preserves_untouched_conditions_and_archive(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    before, _ = resolve_parent(parent, bundle)
    schema = contract.output_schema(bundle, Inventory.model_validate(parent['receipt']['inventory']), parent,
                                    review_request=request)
    jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(response, schema)
    outcome, packet = execute(store, bundle, parent, request, response, mode='condition_review')
    assert outcome['state'] == 'succeeded'
    after, _ = resolve_parent({k: packet[k] for k in ('run_id','receipt','raw_output')}, bundle)
    assert after.states[0].conditions[0] == before.states[0].conditions[0]
    assert after.states[0].conditions[2] == before.states[0].conditions[2]
    audit = packet['receipt']['revision_audit']
    assert audit['unlisted_conditions_unchanged']
    assert len(audit['condition_changes']) == 1
    assert audit['condition_changes'][0]['source_quotes']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    database = ProposalDatabase(tmp_path/'archive')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection, sqlite3.connect(tmp_path/'backup.sqlite3') as backup:
        connection.backup(backup)
        assert not backup.execute('PRAGMA foreign_key_check').fetchall()
        restored = json.loads(backup.execute('SELECT payload FROM runs').fetchone()[0])
        assert restored == packet
        verify_packet(restored)


@pytest.mark.parametrize('mutation', ['omitted_change','silent_deletion','duplicate_change','stale_hash','wrong_action','reordered'])
def test_invalid_condition_transactions_are_retained_without_extraction(tmp_path, mutation):
    store, bundle, parent, request, response = fixture(tmp_path)
    if mutation == 'omitted_change': response['condition_changes'] = []
    if mutation == 'silent_deletion': response['edits'][0]['value']['conditions'].pop(2)
    if mutation == 'duplicate_change': response['condition_changes'] *= 2
    if mutation == 'stale_hash': response['condition_changes'][0]['before_sha256'] = '0'*64
    if mutation == 'wrong_action': response['condition_changes'][0]['action'] = 'remove'
    if mutation == 'reordered': response['edits'][0]['value']['conditions'].reverse()
    outcome, packet = execute(store, bundle, parent, request, response, mode='condition_review')
    assert outcome['state'] == 'quarantined'
    assert 'extraction' not in packet['receipt']
    assert json.loads(packet['raw_output']) == response
    assert not packet['ml_training_eligible']


def test_invalid_source_is_rejected_by_output_schema_and_independent_backend_check(tmp_path):
    _, bundle, parent, request, response = fixture(tmp_path)
    response['condition_changes'][0]['span_ids'] = ['S999']
    schema = contract.output_schema(bundle, Inventory.model_validate(parent['receipt']['inventory']), parent,
                                    review_request=request)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(response, schema)
    with pytest.raises(ValueError):
        contract.apply_edits(parent, bundle, contract.NativeEdits.model_validate(response), review_request=request)


def test_explicit_removal_is_audited_and_never_grants_scientific_acceptance(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    state = response['edits'][0]['value']
    removed = state['conditions'].pop(2)
    for ref in state['evidence']: ref['fields'] = [f for f in ref['fields'] if not f.startswith('/conditions/2')]
    response['condition_changes'].append({'state_id':state['id'], 'condition_id':removed['id'],
        'action':'remove', 'before_sha256':digest(removed),
        'reason':'Explicit deletion proposal for review, not scientific approval.', 'span_ids':['S1']})
    outcome, packet = execute(store, bundle, parent, request, response, mode='condition_review')
    change = next(c for c in packet['receipt']['revision_audit']['condition_changes'] if c['action']=='remove')
    assert change['before'] == removed and change['after'] is None and change['source_quotes']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    tampered = deepcopy(packet['receipt']); tampered['revision_audit']['condition_changes'] = []
    with pytest.raises(ValueError, match='condition_receipt_reconstruction_mismatch'):
        contract.verify_receipt(tampered, bundle, packet['raw_output'])


@pytest.mark.parametrize('via_fields', [False, True])
def test_condition_guard_cannot_be_downgraded_after_exact_literal_selection(tmp_path, via_fields):
    from ingestion.materials_ner import scoped_review, source_field_scoped
    store, bundle, parent, request, response = fixture(tmp_path)
    _, first = execute(store, bundle, parent, request, response, mode='condition_review')
    parent = {k:first[k] for k in ('run_id','receipt','raw_output')}
    graph, _ = resolve_parent(parent, bundle)
    request['parent_run_id'] = parent['run_id']
    if via_fields:
        field_request = dict(deepcopy(request), schema_version='materials-source-field-request/1',
            fields=[{'id':'range-basis','issue_id':'phase-scope','entity':'state','entity_id':graph.states[0].id,
                'field':'/conditions/1/basis_raw','expected_value_sha256':digest('10 to 30 GPa'),
                'kind':'raw_literal','allow_absent':False}])
        selection = {'schema_version':source_field_scoped.VERSION, 'work_id':bundle.work_id,
            'parent_run_id':parent['run_id'], 'base_graph_sha256':digest(graph.model_dump()),
            'request_sha256':digest(field_request), 'selections':[{'target_id':'range-basis','action':'copy',
                'span_ids':['S1'],'exact_text':'10 to 30 GPa','occurrence':None,'reason':'Copy original text.'}]}
        _, packet = execute(store,bundle,parent,field_request,selection,mode='scoped_fields')
        parent = {k:packet[k] for k in ('run_id','receipt','raw_output')}
        graph, _ = resolve_parent(parent,bundle); request['parent_run_id'] = parent['run_id']
    with pytest.raises(ValueError, match='condition_revision_downgrade_forbidden'):
        scoped_review.configuration(parent,review_request=request)
    legacy = dict(response, schema_version=scoped_review.VERSION)
    legacy.pop('condition_changes')
    with pytest.raises(ValueError, match='condition_revision_downgrade_forbidden'):
        scoped_review.apply_edits(parent,bundle,scoped_review.NativeEdits.model_validate(legacy),review_request=request)
    response.update(parent_run_id=parent['run_id'],base_graph_sha256=digest(graph.model_dump()),
                    request_sha256=digest(request),edits=[],condition_changes=[])
    response['dispositions'][0]['status']='unchanged_supported'
    outcome, packet = execute(store,bundle,parent,request,response,mode='condition_review')
    assert outcome['state']=='succeeded'
    assert packet['receipt']['revision_audit']['unlisted_conditions_unchanged']
