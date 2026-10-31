"""Synthetic checks for narrowly authorized field repairs, never scientific Gold."""
from copy import deepcopy
import json
import sqlite3

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import source_field_focus as focus
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.native_revision import configuration, run_one
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.relational_review import pending_review_issues
from ingestion.materials_ner.scoped_review import resolve_parent
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration as initial_config, run_one as initial_run
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_scoped_conditions import fixture as source_fixture


def fixture(tmp_path):
    bundle, inventory, raw = source_fixture()
    bundle.blocks = make_blocks(bundle.documents[0].id, [
        ('synthetic:1', bundle.blocks[0].text),
        ('synthetic:2', 'SYNTHETIC FIXTURE. Sample A is nominal MgB2 in bulk form.')])
    inventory['processed_block_ids'] = raw['processed_block_ids'] = ['B1', 'B2']
    inventory['span_dispositions'].append(dict(span_id='S2', role='context_only', item_ids=[], reason='Sample context.'))
    raw['samples'][0].update(form_raw=None, substrate_raw=None)
    raw['samples'][0]['evidence'][0]['fields'].append('/substrate_raw')
    raw['observations'][0]['result']['quantity']['raw'] = '39'
    raw['additional_items'] = [dict(id='U1', sample_raw='MgB2, synthetic phase',
        quantity_name_raw='fit-domain statement', value_raw='20 to 70 K', source_span_ids=['S1'], context_span_ids=[])]
    raw['unextracted_items'] = [dict(item_id='U1', reason='not_a_result', explanation='Fit domain, pending review.')]
    store = Store(tmp_path); bundle_hash, _ = save_bundle(tmp_path, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=bundle_hash, config=initial_config(workflow='inventory_v9'))
    initial_run(store, job_id=job, provider_override=SequenceProvider([inventory, raw]))
    packet = import_packet(store, job); verify_packet(packet)
    parent = {k: packet[k] for k in ('run_id', 'receipt', 'raw_output')}
    graph, _ = resolve_parent(parent, bundle)
    request = dict(schema_version='materials-source-field-request/2', work_id=bundle.work_id,
        parent_run_id=parent['run_id'], bundle_sha256=bundle_hash, author_kind='assistant', issues=[], fields=[])
    selections = []
    for number, (entity, entity_id, field, value, kind, action, span, text) in enumerate([
        ('sample', graph.samples[0].id, '/target_kind', graph.samples[0].target_kind, 'evidence_binding', 'rebind', 'S2', None),
        ('sample', graph.samples[0].id, '/form_raw', None, 'null_evidence', 'drop_null_binding', 'S1', None),
        ('sample', graph.samples[0].id, '/substrate_raw', None, 'null_evidence', 'drop_null_binding', 'S1', None),
        ('result', graph.observations[0].id, '/result/quantity/raw', '39', 'quantity_literal', 'copy', 'S1', '39 K'),
        ('additional_item', 'U1', '/sample_raw', 'MgB2, synthetic phase', 'raw_literal', 'copy', 'S2', 'MgB2'),
    ]):
        identity = 'F' + str(number)
        request['issues'].append(dict(id=identity, concern='Check the specified field against original source.',
            targets=[dict(entity=entity, entity_id=entity_id)], span_ids=['S1', 'S2']))
        request['fields'].append(dict(id=identity, issue_id=identity, entity=entity, entity_id=entity_id,
            field=field, expected_value_sha256=digest(value), kind=kind, allow_absent=False))
        selections.append(dict(target_id=identity, action=action, span_ids=[span], exact_text=text, occurrence=None,
            reason='Apply the explicit source selection and retain all other fields.'))
    response = dict(schema_version=focus.VERSION, work_id=bundle.work_id, parent_run_id=parent['run_id'],
        base_graph_sha256=digest(graph.model_dump()), request_sha256=digest(request), selections=selections)
    return store, bundle, parent, request, response


def execute(store, bundle, parent, request, response):
    config = configuration(parent, mode='focused_fields', review_request=request)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=parent['receipt']['bundle_sha256'], config=config, max_attempts=1)
    provider = SequenceProvider([response])
    outcome = run_one(store, job, parent, bundle, mode='focused_fields', provider_override=provider)
    assert provider.calls == 1
    packet = import_packet(store, job); verify_packet(packet)
    return outcome, packet


def test_declared_fields_only_and_receipt_database_restore_preserve_scientific_content(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    before, _ = resolve_parent(parent, bundle)
    schema = focus.output_schema(bundle, Inventory.model_validate(parent['receipt']['inventory']), parent, review_request=request)
    jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(response, schema)
    outcome, packet = execute(store, bundle, parent, request, response)
    assert outcome['state'] == 'quarantined'
    next_parent = {k: packet[k] for k in ('run_id', 'receipt', 'raw_output')}
    after, _ = resolve_parent(next_parent, bundle)
    assert len(after.additional_items) == len(before.additional_items) == 1
    assert after.additional_items[0].model_dump() == dict(before.additional_items[0].model_dump(),
        sample_raw='MgB2', context_span_ids=['S2'])
    assert after.observations[0].result.quantity.model_dump(exclude={'raw'}) == before.observations[0].result.quantity.model_dump(exclude={'raw'})
    assert after.observations[0].result.quantity.raw == '39 K'
    assert after.observations[1:] == before.observations[1:]
    for key in ('states', 'protocols', 'sample_relations', 'condition_supports', 'context_dispositions', 'unextracted_items'):
        assert getattr(after, key) == getattr(before, key)
    sample = after.samples[0].model_dump()
    assert {k:v for k,v in sample.items() if k != 'evidence'} == before.samples[0].model_dump(exclude={'evidence'})
    assert not any(field in ('/form_raw', '/substrate_raw') for binding in sample['evidence'] for field in binding['fields'])
    assert [b['span_ids'] for b in sample['evidence'] if '/target_kind' in b['fields']] == [['S2']]
    assert pending_review_issues(next_parent) == request['issues']
    assert all(row['changed'] for row in packet['receipt']['revision_audit']['field_changes'])
    assert not packet['ml_training_eligible'] and not packet['scientific_acceptance']
    db = ProposalDatabase(tmp_path / 'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as connection, sqlite3.connect(tmp_path / 'restore.sqlite3') as backup:
        connection.backup(backup)
        assert not backup.execute('PRAGMA foreign_key_check').fetchall()
        for row in backup.execute('SELECT payload FROM runs'): verify_packet(json.loads(row[0]))
    # A no-op is a valid field decision and cannot require a whole-entity rewrite.
    next_request = dict(deepcopy(request), parent_run_id=packet['run_id'])
    next_request['fields'] = [request['fields'][0]]
    next_response = dict(response, parent_run_id=packet['run_id'], base_graph_sha256=digest(after.model_dump()),
        request_sha256=digest(next_request), selections=[response['selections'][0]])
    revision = focus.apply_edits(next_parent, bundle, focus.NativeEdits.model_validate(next_response), review_request=next_request)
    assert not revision.field_audit[0]['changed'] and revision.revised_graph == after
    omitted = dict(next_request, issues=next_request['issues'][:1])
    with pytest.raises(ValueError, match='drops_or_rewrites_unresolved'):
        focus.validate_request(omitted, next_parent, bundle)


@pytest.mark.parametrize('text', ['37 K', '8 nm', 'unprinted 39 K'])
def test_incompatible_quantity_or_unlocatable_quote_keeps_old_value_and_evidence(tmp_path, text):
    store, bundle, parent, request, response = fixture(tmp_path)
    response['selections'][3]['exact_text'] = text
    _, packet = execute(store, bundle, parent, request, response)
    graph, _ = resolve_parent({k:packet[k] for k in ('run_id','receipt','raw_output')}, bundle)
    assert graph.observations[0] == resolve_parent(parent, bundle)[0].observations[0]
    audit = packet['receipt']['revision_audit']
    assert audit['rejected_field_count'] == 1 and not audit['field_changes'][3]['changed']
    assert audit['field_changes'][3]['selection_error']
    assert graph.additional_items[0].sample_raw == 'MgB2'


@pytest.mark.parametrize('mutation', ['value', 'additional_kind', 'action', 'scope', 'parent', 'duplicate', 'direct_evidence'])
def test_unauthorized_scope_is_rejected_atomically(tmp_path, mutation):
    _, bundle, parent, request, response = fixture(tmp_path)
    if mutation == 'value': request['fields'][3]['field'] = '/result/quantity/value'
    if mutation == 'additional_kind': request['fields'][4]['kind'] = 'evidence_binding'
    if mutation == 'action': response['selections'][0].update(action='copy', exact_text='bulk')
    if mutation == 'scope': response['selections'][0]['span_ids'] = ['S99']
    if mutation == 'parent': response['parent_run_id'] = '0' * 64
    if mutation == 'duplicate': response['selections'][1] = response['selections'][0]
    if mutation == 'direct_evidence': request['fields'][0]['field'] = '/evidence/0/fields'
    response['request_sha256'] = digest(request)
    with pytest.raises((ValueError, KeyError)):
        focus.apply_edits(parent, bundle, focus.NativeEdits.model_validate(response), review_request=request)


def test_undeclared_entity_addition_and_forged_audit_are_rejected(tmp_path):
    store, bundle, parent, request, response = fixture(tmp_path)
    with pytest.raises(ValidationError): focus.NativeEdits.model_validate(dict(response, additional_items=[]))
    _, packet = execute(store, bundle, parent, request, response)
    for mutation in ('graph', 'audit', 'holds'):
        receipt = deepcopy(packet['receipt'])
        if mutation == 'graph': receipt['extraction']['results'][0]['quantity']['value'] = 40
        if mutation == 'audit': receipt['revision_audit']['field_changes'] = []
        if mutation == 'holds': receipt['validation']['issues'] = []
        with pytest.raises(ValueError): focus.verify_receipt(receipt, bundle, packet['raw_output'])
