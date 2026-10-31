"""Actual lost witnesses, incompatible supports and historical replay boundaries."""
from copy import deepcopy

import jsonschema
import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner import identity_stages as identity, item_stages as items, item_worker
from ingestion.materials_ner import owner_witness_stages as witness, staged_revision
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.sources import Bundle, sha
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_identity_stages import fixture, typed
from test_materials_ner_item_stages import parent_packet, StageProvider


def real_fixture():
    raw = private_json('materials_ner_owner_witness_w4.json')
    bundle = Bundle.model_validate(raw['bundle']); inventory = Inventory.model_validate(raw['inventory'])
    output = raw['outputs']; owned = identity.OwnedDeclarations.model_validate(output['declarations'])
    relations = identity.Relations.model_validate(output['catalog-relations'])
    catalog, _ = identity.project(identity.body(owned), relations, bundle)
    plan = identity.project_owners(owned, inventory, bundle)
    group = items.ItemGroup.model_validate(output['items-1']); links = items.ContextLinks.model_validate(output['contexts'])
    return bundle, inventory, owned, relations, catalog, plan, group, links


def invoke(parts):
    bundle, inventory, owned, relations, catalog, plan, group, links = parts
    return witness.assemble(bundle, inventory, catalog, group.decisions, links, owner_plan=plan,
        owner_declarations=owned, catalog_relations=relations)


def test_actual_w4_recovers_twelve_bindings_without_rewriting_any_scientific_value():
    parts = real_fixture(); bundle, inventory, _, _, catalog, plan, group, links = parts
    untouched = digest([x.model_dump() if hasattr(x, 'model_dump') else x for x in parts])
    old, old_coverage, old_proof = identity.assemble(bundle, inventory, catalog, group.decisions, links, owner_plan=plan)
    new, coverage, proof = invoke(parts)
    old_issues = validate_extraction(old.expand(bundle), bundle)['issues']+old_coverage['issues']
    new_issues = validate_extraction(new.expand(bundle), bundle)['issues']+coverage['issues']
    lost = [i for i in old_issues if i not in new_issues]
    assert len(lost) == 12
    assert all(i['code'] == 'field_evidence_missing' and i['path'].rsplit('/',1)[1] in
        {'sample_id','state_id','protocol_id'} for i in lost)
    assert all(i in old_issues for i in new_issues)
    assert sum(i['code'] == 'condition_support_quantity_kind_mismatch' for i in new_issues) == 2
    assert any(i['code'] == 'source_literal_not_in_field_evidence' for i in new_issues)
    expected = new.model_dump()
    for obs, original in zip(expected['observations'], old.model_dump()['observations']):
        obs['result']['evidence'] = original['result']['evidence']
    assert expected == old.model_dump()
    assert untouched == digest([x.model_dump() if hasattr(x, 'model_dump') else x for x in parts])
    ledger = proof['owner_witness_transport']
    assert sum(len(e['appended_fields']) for e in ledger['entries']) == 12
    assert not ledger['scientific_ownership_verified'] and ledger['scientific_payload_unchanged']
    assert proof['schema'] == 'materials-source-item-assembly/3'
    assert old_proof['schema'] == 'materials-source-item-assembly/2'
    assert new.model_dump() == invoke(parts)[0].model_dump()


@pytest.mark.parametrize('change', ['witness','owners','selection_hash','inventory','source','catalog','item_id','declarations'])
def test_transport_rejects_substituted_source_owner_catalog_or_prior_selection(change):
    parts = list(real_fixture()); bundle, inventory, owned, _, catalog, plan, group, _ = parts
    if change == 'witness': plan['items']['I1']['source_span_ids'] = ['S19']
    elif change == 'owners': group.decisions['I1'].observation.state_id = 'state:1:2'
    elif change == 'selection_hash': plan['declarations_sha256'] = '0'*64
    elif change == 'inventory': inventory.items[0].value_raw = '43 T'
    elif change == 'source':
        bundle.blocks[0].text += '\nSubstituted source.'; bundle.blocks[0].sha256 = sha(bundle.blocks[0].text.encode())
    elif change == 'catalog': catalog.samples[0].label = 'Another specimen'
    elif change == 'item_id': plan['items']['I9'] = plan['items'].pop('I1')
    else: owned.item_owners['I1'].source_span_ids = ['S19']
    with pytest.raises(ValueError): invoke(parts)


def test_held_items_get_no_owner_witness_and_remain_held():
    parts = list(real_fixture()); parts[-1] = None
    parts[-2].decisions['I1'] = items.ItemGroup.model_validate(dict(schema_version='materials-source-item-group/1',
        work_id=parts[0].work_id, decisions={'I1':dict(decision='held',reason='insufficient_context',
            explanation='The owner remains unresolved.') })).decisions['I1']
    graph, _, proof = invoke(parts)
    assert graph.completion.outcome == 'incomplete'
    assert len(graph.observations) == 3 and graph.unextracted_items[0].item_id == 'I1'
    assert all(x['item_id'] != 'I1' for x in proof['owner_witness_transport']['entries'])


def test_actual_tc_field_edges_are_excluded_from_generation_but_still_rejected_if_bypassed():
    bundle, inventory, _, _, catalog, _, group, links = real_fixture()
    graph = items.graph_objects(catalog, group.decisions)
    assert witness.support_choices(graph) == []
    old = items.links_schema(bundle, inventory, graph)
    jsonschema.validate(links.model_dump(), old)
    schema = witness.links_schema(bundle, inventory, graph)
    jsonschema.Draft202012Validator.check_schema(schema)
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(links.model_dump(), schema)
    data = links.model_dump(); data['condition_supports'] = []
    jsonschema.validate(data, schema)


def support_fixture():
    bundle, inventory, _, catalog, _, group, _ = typed()
    graph = items.graph_objects(catalog, group.decisions); first = graph['observations'][0]
    state = next(x for x in graph['states'] if x['id'] == first['state_id'])
    condition = state['conditions'][0]
    condition.update(kind='thickness', quantity=dict(status='reported',raw='20 nm',unit='nm',relation='exact',
        value=20,lower=None,upper=None,approximate=False,uncertainty=None))
    first['result'].update(quantity_kind='thickness',origin='observed',quantity=dict(condition['quantity']))
    support = dict(result_id=first['id'], state_id=state['id'], condition_id=condition['id'],relation='measures',
        relation_raw='Synthetic support assertion',evidence=[dict(fields=['/result_id','/state_id','/condition_id','/relation','/relation_raw'],span_ids=['S1'])])
    return bundle, inventory, graph, support


@pytest.mark.parametrize('change', ['same','converted','different_value','different_kind','bad_unit','computed','no_method','uncertainty'])
def test_support_generation_requires_same_registered_quantity_and_preserves_valid_unit_conversion(change):
    bundle, inventory, graph, support = support_fixture(); observation = graph['observations'][0]
    result = observation['result']
    if change == 'converted': result['quantity'].update(raw='200 Å',unit='Å',value=200)
    elif change == 'different_value': result['quantity']['value'] = 21
    elif change == 'different_kind': result['quantity_kind'] = 'coherence_length'
    elif change == 'bad_unit': result['quantity']['unit'] = 'K'
    elif change == 'computed': result['origin'] = 'computed'
    elif change == 'no_method': next(p for p in graph['protocols'] if p['id']==observation['protocol_id'])['method'] = None
    elif change == 'uncertainty': result['quantity']['approximate'] = True
    candidates = witness.support_choices(graph)
    ids = {k:support[k] for k in ('result_id','state_id','condition_id')}
    assert (ids in candidates) == (change in {'same','converted'})
    schema = witness.links_schema(bundle, inventory, graph)
    if change in {'same','converted'}:
        jsonschema.validate(support,{'$defs':schema['$defs'], '$ref':'#/$defs/SourceSupport'})
        support['evidence'][0]['fields'] = ['/quantity']
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(support,{'$defs':schema['$defs'], '$ref':'#/$defs/SourceSupport'})


@pytest.mark.parametrize('failure', [None, 2, 4])
def test_worker_receipt_private_archive_revision_and_failed_stage_replay(tmp_path, failure):
    parent, _, _, _, _ = parent_packet(tmp_path/'parent')
    bundle, inventory, raw, relations, decisions, links = fixture(); keys = list(decisions)
    outputs = [raw, relations, *[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k: decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)],links]
    store = Store(tmp_path/'staged')
    job = item_worker.enqueue(store,parent,workflow=identity.WORKFLOW,field_generation_policy=witness.POLICY)
    outcome = run_one(store,job_id=job,provider_override=StageProvider(outputs,fail_at=failure))
    assert outcome['state'] == ('failed' if failure else 'succeeded'), outcome
    packet = import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['config']['prompt_version'] == witness.PROMPT_VERSION
    db = ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    if not failure:
        graph, _ = staged_revision.resolve_parent(packet)
        assert graph.expand(bundle).model_dump() == packet['receipt']['extraction']
        damaged = deepcopy(packet['receipt']); damaged['staged_assembly']['owner_witness_transport']['entries'][0]['source_witness_sha256'] = '0'*64
        with pytest.raises(ValueError,match='assembly_mismatch'):
            item_worker.verify_receipt(damaged,bundle,packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
