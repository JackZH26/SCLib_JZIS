"""Staged object fidelity, incomplete-work retention and immutable replay."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import item_stages as stages, item_worker
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.providers import ProviderFailure, ProviderResult
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_non_detection_targets import fixture as old_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture():
    bundle, inventory, old = old_fixture()
    catalog = {key: old[key] for key in ('work_id', 'processed_block_ids', 'unread_block_ids',
        'limitations', 'samples', 'states', 'protocols', 'sample_relations')}
    catalog = deepcopy(catalog)
    catalog.update(schema_version='materials-source-entity-catalog/1', additional_source_items=[], no_result_reason=None)
    names = {o['id']: stages.result_id(o['inventory_item_ids'][0]) for o in old['observations']}
    decisions = {}
    for original in old['observations']:
        observation = deepcopy(original); item_id = observation.pop('inventory_item_ids')[0]
        observation.pop('id')
        for dep in observation['result']['dependencies']: dep['result_id'] = names[dep['result_id']]
        decisions[item_id] = {'decision': 'emitted', 'observation': observation}
    links = {'schema_version': 'materials-source-context-links/1', 'work_id': bundle.work_id,
             'contexts': {}, 'condition_supports': []}
    for disposition in old['context_dispositions']:
        body = deepcopy(disposition); key = body.pop('context_id')
        for binding in body['bindings']:
            if binding['entity'] in {'result', 'definition'}: binding['entity_id'] = names[binding['entity_id']]
        links['contexts'][key] = body
    for support in old['condition_supports']:
        support = deepcopy(support); support.pop('id'); support['result_id'] = names[support['result_id']]
        links['condition_supports'].append(support)
    return bundle, Inventory.model_validate(inventory), old, catalog, decisions, links


def typed():
    bundle, inventory, old, catalog, decisions, links = fixture()
    catalog = stages.EntityCatalog.model_validate(catalog)
    group = stages.ItemGroup(schema_version='materials-source-item-group/1', work_id=bundle.work_id, decisions=decisions)
    return bundle, inventory, old, catalog, group.decisions, stages.ContextLinks.model_validate(links)


def test_stages_preserve_actual_scientific_objects_and_shared_entities():
    bundle, inventory, old, catalog, decisions, links = typed()
    for schema, payload in [
        (stages.catalog_schema(bundle), catalog.model_dump()),
        (stages.item_schema(bundle, catalog, list(decisions), inventory.items),
         {'schema_version': 'materials-source-item-group/1', 'work_id': bundle.work_id,
          'decisions': {k: v.model_dump() for k, v in decisions.items()}}),
        (stages.links_schema(bundle, inventory, stages.graph_objects(catalog, decisions)), links.model_dump()),
    ]:
        jsonschema.Draft202012Validator.check_schema(schema); jsonschema.validate(payload, schema)
    graph, coverage, proof = stages.assemble(bundle, inventory, catalog, decisions, links)
    assert coverage['valid'], coverage['issues']
    assert validate_extraction(graph.expand(bundle), bundle)['valid']
    assert graph.completion.outcome == 'results'
    assert [s.model_dump() for s in graph.samples] == old['samples']
    assert [s.model_dump() for s in graph.states] == old['states']
    assert [p.model_dump() for p in graph.protocols] == old['protocols']
    for observation in graph.observations:
        key = observation.inventory_item_ids[0]
        assert observation.model_dump(exclude={'id', 'inventory_item_ids'}) == decisions[key].observation.model_dump()
        assert observation.id == stages.result_id(key)
    assert not proof['scientific_acceptance'] and not proof['source_semantic_coverage_verified']


@pytest.mark.parametrize('mutation', ['no_object', 'invented_protocol', 'wrong_state', 'missing_key', 'extra_key'])
def test_emitted_slots_cannot_be_filled_by_a_plan_or_a_foreign_reference(mutation):
    bundle, inventory, _, catalog, decisions, _ = fixture()
    catalog = stages.EntityCatalog.model_validate(catalog); ids = list(decisions)
    if mutation == 'no_object': decisions[ids[0]] = {'decision': 'emitted', 'result_id': 'planned-R1'}
    if mutation == 'invented_protocol': decisions[ids[0]]['observation']['protocol_id'] = 'phantom'
    if mutation == 'wrong_state': decisions[ids[0]]['observation']['state_id'] = 'phantom'
    if mutation == 'missing_key': decisions.pop(ids[0])
    if mutation == 'extra_key': decisions['extra'] = deepcopy(decisions[ids[0]])
    data = {'schema_version': 'materials-source-item-group/1', 'work_id': bundle.work_id, 'decisions': decisions}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, stages.item_schema(bundle, catalog, ids, inventory.items))
    if mutation == 'no_object':
        with pytest.raises(ValidationError): stages.ItemGroup.model_validate(data)
    else:
        with pytest.raises(ValueError): stages.check_group(stages.ItemGroup.model_validate(data), ids, catalog, bundle.work_id)


def test_duplicate_keys_never_drop_a_source_decision():
    with pytest.raises(ValueError, match='staged_duplicate_json_key'):
        stages.parse_response(stages.ItemGroup, '{"decisions":{"I1":{},"I1":{}}}')


@pytest.mark.parametrize('entity', ['samples', 'states', 'protocols'])
def test_catalog_generation_rejects_bare_evidence_field_names(entity):
    bundle, _, _, catalog, _, _ = fixture()
    reference = catalog[entity][0]['evidence'][0]
    reference['fields'][0] = reference['fields'][0].lstrip('/')
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(catalog, stages.catalog_schema(bundle))


def test_catalog_rejects_a_planned_but_absent_condition_use():
    _, _, _, catalog, _, _ = fixture()
    catalog['protocols'][0]['context_uses'] = [{
        'state_id': catalog['states'][0]['id'], 'condition_id': 'unemitted_fit_window'}]
    with pytest.raises(ValidationError, match='invalid_stable_condition_method_use'):
        stages.EntityCatalog.model_validate(catalog)


@pytest.mark.parametrize('mutation', ['phantom', 'absent_field', 'definition_on_result', 'missing_context'])
def test_contexts_only_target_present_fields_on_actual_objects(mutation):
    bundle, inventory, _, catalog, decisions, links = typed()
    graph = stages.graph_objects(catalog, decisions)
    raw = links.model_dump()
    first_key = next(iter(raw['contexts']))
    if mutation == 'missing_context': raw['contexts'].pop(first_key)
    else:
        raw['contexts'][first_key] = {'resolution': 'carried', 'explanation': None, 'bindings': [{
            'entity': 'result', 'entity_id': 'phantom' if mutation == 'phantom' else 'item:I1',
            'field': '/definition/criterion' if mutation == 'definition_on_result' else '/not_a_field'}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw, stages.links_schema(bundle, inventory, graph))
    with pytest.raises(ValueError): stages.check_links(stages.ContextLinks.model_validate(raw), inventory, graph)


def test_failed_or_unattempted_items_remain_explicit_system_holds():
    bundle, inventory, _, catalog, decisions, _ = typed()
    chosen = {key: decisions[key] for key in list(decisions)[:2]}; missing = list(decisions)[2:]
    graph, coverage, proof = stages.assemble(bundle, inventory, catalog, chosen, None,
        missing_item_ids=missing, stage_failures=[{'stage': 'items-2', 'code': 'provider_failed'}])
    assert graph.completion.outcome == 'incomplete' and len(graph.observations) == 2
    assert proof['missing_item_ids'] == missing and len(proof['system_holds']) == len(missing)
    assert all(h['explanation'].startswith('System:') for h in proof['system_holds'])
    assert not coverage['valid']


def test_model_exclusion_never_becomes_a_successful_empty_and_cannot_erase_source():
    bundle, inventory, _, catalog, decisions, _ = typed()
    decisions = {key: stages.HeldItem(decision='held', reason='not_a_result', explanation='Requires source review.') for key in decisions}
    graph, _, proof = stages.assemble(bundle, inventory, catalog, decisions, None)
    assert graph.completion.outcome == 'incomplete' and graph.observations == []
    assert len(graph.unextracted_items) == len(inventory.items)
    assert not proof['scientific_acceptance']


def test_additional_source_assertions_keep_collision_free_ids_and_literal_values():
    bundle, inventory, _, catalog, _, _ = typed()
    inventory.items[0].id = 'additional:1'
    catalog.additional_source_items = [stages.SourceAddition.model_validate(inventory.items[0].model_dump(exclude={'id'}))]
    items, added = stages.inventory_items(inventory, catalog)
    assert added[0].id == 'additional:additional:1'
    assert added[0].value_raw == inventory.items[0].value_raw
    assert len(items) == len(inventory.items)+1
    catalog.additional_source_items[0].value_raw = 'invented 99999'
    with pytest.raises(ValueError, match='staged_additional_value_not_in_source'):
        stages.check_catalog(catalog, inventory, bundle, 64)


def parent_packet(tmp_path):
    bundle, inventory, old, catalog, decisions, links = fixture()
    store = Store(tmp_path/'parent'); key, _ = save_bundle(store.root, bundle)
    job = store.enqueue(work_id=bundle.work_id, bundle_hash=key, config=configuration(workflow='inventory_v10'))
    assert run_one(store, job_id=job, provider_override=SequenceProvider([inventory.model_dump(), old]))['state'] == 'succeeded'
    return import_packet(store, job), bundle, catalog, decisions, links


class StageProvider:
    def __init__(self, responses, fail_at=None): self.responses = responses; self.calls = 0; self.fail_at = fail_at
    def extract(self, prompt, schema, config, directory):
        self.calls += 1
        if self.calls == self.fail_at: raise ProviderFailure('synthetic_provider_failure')
        value = self.responses[self.calls-1]
        jsonschema.validate(value, schema)
        return ProviderResult(canonical(value), {'input_tokens': 10, 'output_tokens': 5}, 'synthetic', 'gpt-6-luna', str(self.calls), .01)


def responses(bundle, catalog, decisions, links):
    ids = list(decisions)
    return [catalog, *[{'schema_version': 'materials-source-item-group/1', 'work_id': bundle.work_id,
        'decisions': {key: decisions[key] for key in ids[index:index+2]}} for index in range(0, len(ids), 2)], links]


@pytest.mark.parametrize('fail_at', [None, 3])
def test_actual_worker_dispatch_private_import_and_partial_provider_failure_replay(tmp_path, fail_at):
    parent, bundle, catalog, decisions, links = parent_packet(tmp_path)
    store = Store(tmp_path/'staged')
    job = item_worker.enqueue(store, parent, group_size=2)
    provider = StageProvider(responses(bundle, catalog, decisions, links), fail_at=fail_at)
    outcome = run_one(store, job_id=job, provider_override=provider)
    assert outcome['state'] == ('failed' if fail_at else 'succeeded'), outcome
    packet = import_packet(store, job); verify_packet(packet)
    assert packet['receipt']['raw_output_kind'] == 'assembled_stage_transcript'
    assert len(packet['rows']['results']) == (2 if fail_at else 5)
    if fail_at: assert packet['receipt']['staged_assembly']['missing_item_ids'] == ['I3', 'I4', 'I5']
    database = ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0]) == packet
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    changed = deepcopy(packet['receipt']); changed['staged_assembly']['result_ids']['I1'] = 'invented'
    with pytest.raises(ValueError, match='staged_receipt_assembly_mismatch'):
        item_worker.verify_receipt(changed, bundle, packet['raw_output'])
    changed = deepcopy(packet['receipt']); changed['stages'][0]['prompt_sha256'] = '0'*64
    with pytest.raises(ValueError, match='staged_receipt_input_hash_mismatch'):
        item_worker.verify_receipt(changed, bundle, packet['raw_output'])
