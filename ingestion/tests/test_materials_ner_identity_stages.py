"""Versioned missing chemistry, stable IDs and actual worker/revision recovery."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import identity_stages as identity, item_stages as items, item_worker
from ingestion.materials_ner import staged_revision as revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.worker import run_one, configuration
from ingestion.materials_ner.sources import save_bundle
from test_materials_ner_item_ownership import fixture as old_fixture
from test_materials_ner_item_stages import parent_packet, StageProvider


def fixture():
    bundle, inventory, raw, relations, decisions, links = old_fixture()
    raw['schema_version'] = 'materials-owned-source-declarations/2'
    for sample in raw['samples']:
        sample.update(formula_raw=None, composition_basis='unresolved', identity_resolution='unresolved',
            formula_unavailability=dict(status='ambiguous',
                explanation='The contextual formula is not assigned to this source-scoped specimen.',
                checked_block_ids=list(source_catalog(bundle)['blocks'])))
        for ref in sample['evidence']:
            ref['fields'] = [f for f in ref['fields'] if f not in {'/formula_raw', '/composition_basis'}]
        sample['evidence'] = [r for r in sample['evidence'] if r['fields']]
    return bundle, inventory, raw, relations, decisions, links


def typed():
    bundle, inventory, raw, relations, decisions, links = fixture()
    owned = identity.OwnedDeclarations.model_validate(raw)
    catalog, _ = identity.project(identity.body(owned), identity.Relations.model_validate(relations), bundle)
    plan = identity.project_owners(owned, inventory, bundle)
    group = items.ItemGroup(schema_version='materials-source-item-group/1', work_id=bundle.work_id, decisions=decisions)
    return bundle, inventory, owned, catalog, plan, group, items.ContextLinks.model_validate(links)


def test_missing_chemistry_survives_stable_ids_and_lossless_attribution_transport():
    bundle, inventory, owned, catalog, plan, group, links = typed()
    before = deepcopy(group.model_dump())
    jsonschema.validate(owned.model_dump(), identity.owner_schema(bundle, inventory))
    graph, coverage, proof = identity.assemble(bundle, inventory, catalog, group.decisions, links, owner_plan=plan)
    canonical = graph.expand(bundle)
    assert coverage['valid'] and validate_extraction(canonical, bundle)['valid']
    assert canonical.schema_version == 'materials-ner/9'
    assert all(s.formula_raw is None and s.formula_unavailability.status == 'ambiguous' for s in canonical.samples)
    assert all(s.formula_unavailability.checked_block_ids == [b.id for b in bundle.blocks] for s in canonical.samples)
    assert group.model_dump() == before
    assert proof['result_ids'] == {key: 'item:'+key for key in group.decisions}
    assert len(proof['attribution_witness_transport']['entries']) == len(group.decisions)
    for observation in graph.observations:
        key = observation.id.removeprefix('item:')
        old = group.decisions[key].observation.model_dump()
        new = observation.model_dump(exclude={'id', 'inventory_item_ids'})
        assert new['sample_id'] == old['sample_id'] and new['state_id'] == old['state_id']
        assert new['result']['quantity'] == old['result']['quantity']
        assert {'fields': ['/source_role'], 'span_ids': plan['items'][key]['attribution']['source_span_ids']} in new['result']['evidence']
    assert all(not r['eligible'] and 'formula_unavailable_ambiguous' in r['reason_codes']
        for r in training_exclusions(canonical, bundle, validate_extraction(canonical, bundle))['results'])
    assert not proof['attribution_witness_transport']['scientific_attribution_verified']


@pytest.mark.parametrize('mutation', ['selected_basis', 'no_status', 'placeholder', 'unread', 'foreign_scope'])
def test_invalid_missingness_remains_a_failure_in_staged_projection(mutation):
    bundle, inventory, owned, _, _, group, links = typed()
    body = identity.body(owned); sample = body.samples[0]
    if mutation == 'selected_basis': sample.composition_basis = 'nominal'
    elif mutation == 'no_status': sample.formula_unavailability = None
    elif mutation == 'placeholder': sample.formula_raw = 'unknown'; sample.formula_unavailability = None
    elif mutation == 'unread': body.unread_block_ids = body.processed_block_ids; body.processed_block_ids = []
    else: sample.formula_unavailability.checked_block_ids = ['B999999']
    with pytest.raises((ValidationError, KeyError)):
        catalog, _ = identity.declare(body)
        identity.assemble(bundle, inventory, catalog, group.decisions, links)[0].expand(bundle)


@pytest.mark.parametrize('field', ['sample_id', 'state_id', 'protocol_id', 'source_role', 'cited_source_raw'])
def test_attribution_transport_never_changes_or_accepts_an_unselected_owner(field):
    bundle, inventory, _, catalog, plan, group, links = typed()
    observation = next(iter(group.decisions.values())).observation
    if field.endswith('_id'): setattr(observation, field, 'another-owner')
    else: setattr(observation.result, field, 'cited' if field == 'source_role' else 'invented')
    with pytest.raises(ValueError):
        identity.assemble(bundle, inventory, catalog, group.decisions, links, owner_plan=plan)


def execute(tmp_path, failure=None):
    parent, _, _, _, _ = parent_packet(tmp_path/'parent')
    bundle, inventory, raw, relations, decisions, links = fixture()
    keys = list(decisions)
    outputs = [raw, relations, *[dict(schema_version='materials-source-item-group/1', work_id=bundle.work_id,
        decisions={k: decisions[k] for k in keys[i:i+4]}) for i in range(0, len(keys), 4)], links]
    store = Store(tmp_path/'identity')
    job = item_worker.enqueue(store, parent, workflow=identity.WORKFLOW)
    outcome = run_one(store, job_id=job, provider_override=StageProvider(outputs, fail_at=failure))
    packet = import_packet(store, job); verify_packet(packet)
    return outcome, packet, bundle, store


@pytest.mark.parametrize('failure', [None, 2, 4])
def test_worker_terminal_receipt_replay_and_private_database_preserve_identity(tmp_path, failure):
    outcome, packet, bundle, _ = execute(tmp_path, failure)
    assert outcome['state'] == ('failed' if failure else 'succeeded'), outcome
    receipt = packet['receipt']
    assert receipt['config']['output_format'] == identity.OUTPUT_FORMAT
    assert receipt['config']['item_owner_policy'] == identity.POLICY
    assert len(packet['rows']['results']) == {None: 5, 2: 0, 4: 4}[failure]
    db = ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as connection:
        assert not connection.execute('pragma foreign_key_check').fetchall()
        assert connection.execute('pragma integrity_check').fetchone()[0] == 'ok'
        for row in connection.execute('select payload from samples'):
            assert json.loads(row[0])['payload']['formula_raw'] is None
    if not failure:
        graph, _ = revision.resolve_parent(packet)
        assert graph.expand(bundle).model_dump() == receipt['extraction']
        damaged = deepcopy(receipt)
        damaged['staged_assembly']['attribution_witness_transport']['entries'][0]['source_span_ids'] = ['S99999']
        with pytest.raises(ValueError, match='assembly_mismatch'):
            item_worker.verify_receipt(damaged, bundle, packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_shared8_parent_is_explicitly_allowed_only_by_new_stages(tmp_path):
    from test_materials_ner_formula_missingness import fixture as initial_fixture
    from test_materials_ner_inventory_v2 import SequenceProvider
    bundle, inventory, raw = initial_fixture()
    store = Store(tmp_path); key, _ = save_bundle(store.root, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=key, config=configuration(workflow='inventory_v12'))
    run_one(store, job_id=job, provider_override=SequenceProvider([inventory.model_dump(), raw]))
    packet = import_packet(store, job)
    assert item_worker.verify_parent(packet, workflow=identity.WORKFLOW) == inventory
    assert item_worker.configuration(packet, workflow=identity.WORKFLOW)['output_format'] == identity.OUTPUT_FORMAT
    for workflow in ('source_item_stages_v1', 'source_item_stages_v2'):
        with pytest.raises(ValueError, match='parent_format_not_supported'):
            item_worker.configuration(packet, workflow=workflow)


@pytest.mark.parametrize('field,value', [('workflow', 'source_item_stages_v2'), ('item_owner_policy', None),
    ('item_owner_policy', 'source_item_owners_references_v3')])
def test_new_receipt_cannot_silently_switch_to_an_older_contract_or_policy(field, value):
    from ingestion.materials_ner.item_flow_v2 import interfaces
    config = dict(output_format=identity.OUTPUT_FORMAT, workflow=identity.WORKFLOW, item_owner_policy=identity.POLICY)
    config[field] = value
    with pytest.raises(ValueError, match='staged_identity_configuration_mismatch'):
        interfaces(config)


def test_field_revision_and_ancestry_keep_ner9_without_downcasting(tmp_path):
    from test_materials_ner_staged_revision import execute as revise
    _, parent, bundle, store = execute(tmp_path)
    graph, _ = revision.resolve_parent(parent)
    value = graph.observations[0].result.source_role
    request = dict(schema_version=revision.REQUEST_VERSION, parent_run_id=parent['run_id'], author_kind='assistant',
        fields=[dict(id='role', path='/observations/0/result/source_role', expected_value_sha256=digest(value),
            operation='replace', concern='Re-read the source attribution without changing chemistry.', source_span_ids=['S1'])],
        source_context=None, prior_revision_run_ids=[])
    response = dict(schema_version=revision.VERSION, work_id=bundle.work_id, parent_run_id=parent['run_id'],
        base_graph_sha256=digest(graph.model_dump()), request_sha256=digest(request), read_context_block_ids=[],
        selections={'role': dict(action='unchanged_supported', value=None, span_ids=['S1'],
            reason='The synthetic source supports the retained attribution.')})
    outcome, packet = revise(store, bundle, parent, request, response)
    assert outcome['state'] == 'quarantined'
    after, _ = revision.resolve_parent(packet)
    assert after.model_dump() == graph.model_dump()
    assert after.expand(bundle).schema_version == 'materials-ner/9'
    assert not packet['ml_training_eligible']
