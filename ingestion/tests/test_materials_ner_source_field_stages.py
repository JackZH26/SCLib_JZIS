"""Scoped evidence generation and immutable source-only inventory projections."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner import source_field_stages as fields, identity_stages as identity, item_stages as items
from ingestion.materials_ner import item_worker, staged_revision
from ingestion.materials_ner.contract import digest, canonical
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.worker import run_one
from test_materials_ner_identity_stages import fixture, typed
from test_materials_ner_item_stages import parent_packet, StageProvider


def test_legitimate_evidence_and_numeric_quantities_remain_unchanged():
    bundle, inventory, raw, relations, decisions, links = fixture()
    schema = fields.owner_schema(bundle, inventory)
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(raw, schema)
    _, _, owned, catalog, plan, group, _ = typed()
    output = fields.item_schema(bundle, catalog, list(decisions), inventory.items, plan=plan)
    jsonschema.Draft202012Validator.check_schema(output);jsonschema.validate(group.model_dump(), output)
    assert fields.project(identity.body(owned), identity.Relations.model_validate(relations), bundle) == identity.project(identity.body(owned), identity.Relations.model_validate(relations), bundle)
    assert fields.inventory_ledger(inventory)['items'][0]['value_raw'] == inventory.items[0].value_raw


@pytest.mark.parametrize('owner,path', [
    ('state','/sample_index'), ('state','/conditions'), ('state','/conditions/0/not_a_field'),
    ('sample','/state_id'), ('sample','/states/0/label'), ('sample','/formula_raw'),
    ('protocol','/criterion'), ('protocol','/context_uses/0'), ('protocol','/id')])
def test_declarations_reject_invented_cross_owner_null_or_unindexed_evidence(owner, path):
    bundle, inventory, raw, _, _, _ = fixture()
    entity = raw['samples'][0]['states'][0] if owner == 'state' else raw['samples'][0] if owner == 'sample' else raw['protocols'][0]
    entity['evidence'][0]['fields'] = [path]
    # Historical generation remains unchanged; new generation prevents these paths.
    jsonschema.validate(raw, identity.owner_schema(bundle, inventory))
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw, fields.owner_schema(bundle, inventory))


def test_null_method_is_allowed_without_positive_method_evidence():
    bundle, inventory, raw, _, _, _ = fixture()
    protocol = raw['protocols'][0];protocol.update(method=None, method_class='unspecified')
    for ref in protocol['evidence']:ref['fields'] = [f for f in ref['fields'] if f != '/method']
    protocol['evidence'] = [r for r in protocol['evidence'] if r['fields']]
    jsonschema.validate(raw, fields.owner_schema(bundle, inventory))
    protocol['evidence'].append(dict(fields=['/method'], span_ids=['S1']))
    jsonschema.validate(raw, identity.owner_schema(bundle, inventory))
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw, fields.owner_schema(bundle, inventory))


@pytest.mark.parametrize('owner,path', [('observation','/quantity'), ('result','/sample_index'),
    ('result','/definition/criterion'), ('definition','/source_role')])
def test_item_evidence_is_scoped_inside_the_selected_owner_branches(owner, path):
    bundle, inventory, _, catalog, plan, group, _ = typed()
    raw = group.model_dump();observation = next(iter(raw['decisions'].values()))['observation']
    entity = observation if owner == 'observation' else observation[owner]
    entity.setdefault('evidence',[]).append(dict(fields=[path], span_ids=['S1']))
    schema = fields.item_schema(bundle, catalog, list(group.decisions), inventory.items, plan=plan)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw, schema)


def test_prompts_omit_fallible_inventory_prose_but_keep_exact_source_and_coordinates():
    bundle, inventory, owned, catalog, plan, group, _ = typed()
    before = digest(inventory.model_dump());inventory = inventory.model_copy(deep=True)
    for item in inventory.items:
        item.sample_raw = 'SYNTHETIC_UNSUPPORTED_SAMPLE_IDENTITY'
        item.quantity_name_raw = 'SYNTHETIC_UNSUPPORTED_RESULT_NAME'
    for context in inventory.context_assertions:context.description = 'SYNTHETIC_UNSUPPORTED_CITATION_PREMISE'
    inventory.limitations = ['SYNTHETIC_UNSUPPORTED_CITATION_PREMISE']
    frozen = digest(inventory.model_dump());graph = items.graph_objects(catalog, group.decisions)
    prompts = [fields.render_declarations(bundle, inventory), fields.render_items(bundle, inventory, catalog, list(group.decisions), plan),
        fields.render_relations(bundle, inventory, catalog), fields.render_links(bundle, inventory, graph)]
    for prompt in prompts:
        assert 'SYNTHETIC_UNSUPPORTED' not in prompt
        for block in bundle.blocks:assert block.text in prompt
    assert inventory.items[0].source_span_ids == fields.inventory_ledger(inventory)['items'][0]['source_span_ids']
    assert digest(inventory.model_dump()) == frozen != before
    assert 'SYNTHETIC_UNSUPPORTED' in identity.render_declarations(bundle, inventory)


@pytest.mark.parametrize('failure',[None,2,4])
def test_real_worker_interface_retains_policy_receipts_and_revision_ancestry(tmp_path, failure):
    parent, _, _, _, _ = parent_packet(tmp_path/'parent')
    bundle, inventory, raw, relations, decisions, links = fixture();keys = list(decisions)
    outputs = [raw, relations, *[dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,
        decisions={k:decisions[k] for k in keys[i:i+4]}) for i in range(0,len(keys),4)], links]
    store = Store(tmp_path/'staged')
    job = item_worker.enqueue(store,parent,workflow=identity.WORKFLOW,field_generation_policy=fields.POLICY)
    outcome = run_one(store,job_id=job,provider_override=StageProvider(outputs,fail_at=failure))
    assert outcome['state'] == ('failed' if failure else 'succeeded'),outcome
    packet = import_packet(store,job);verify_packet(packet);receipt = packet['receipt'];config = receipt['config']
    assert config['field_generation_policy'] == fields.POLICY and config['prompt_version'] == fields.PROMPT_VERSION
    assert config['prompt_inventory_projection_sha256'] == digest(fields.inventory_ledger(inventory))
    assert receipt['inventory'] == parent['receipt']['inventory']
    db = ProposalDatabase(tmp_path/'archive');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    if not failure:
        graph, _ = staged_revision.resolve_parent(packet)
        assert graph.expand(bundle).model_dump() == receipt['extraction']
        damaged = deepcopy(receipt);damaged['config']['prompt_inventory_projection_sha256'] = '0'*64
        with pytest.raises(ValueError,match='prompt_inventory_projection_mismatch'):
            item_worker.verify_receipt(damaged,bundle,packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    for workflow in ('source_item_stages_v1','source_item_stages_v2'):
        with pytest.raises(ValueError,match='field_generation_policy_unknown'):
            item_worker.configuration(parent,workflow=workflow,field_generation_policy=fields.POLICY)


def test_zero_temperature_limit_never_passes_as_a_reported_field_condition():
    from ingestion.materials_ner.sources import Block, sha
    bundle, inventory, owned, catalog, plan, group, links = typed()
    text = r'Our upper critical field is evaluated when $T$ $\rightarrow$ 0.'
    bundle.blocks.append(Block(id='limit',document_id=bundle.documents[0].id,ordinal=100,locator='synthetic:limit',text=text,sha256=sha(text.encode())))
    graph, _, _ = identity.assemble(bundle,inventory,catalog,group.decisions,links)
    expanded = graph.expand(bundle)
    condition = expanded.states[0].conditions[0]
    condition.kind = 'magnetic_flux_density'
    condition.quantity = type(condition.quantity)(status='reported',raw=r'when $T$ $\rightarrow$ 0',unit='T',relation='exact',
        value=0,lower=None,upper=None,approximate=False,uncertainty=None)
    state = expanded.states[0]
    witness = state.evidence[0].model_copy(update=dict(block_id='limit',quote=text,field='/conditions/0'))
    state.evidence = [ref for ref in state.evidence if not ref.field.startswith('/conditions/0')]+[witness]
    issues = validate_extraction(expanded,bundle)['issues']
    assert any(i['code']=='numeric_raw_requires_review' and i['path']=='/states/0/conditions/0/quantity' for i in issues)
    assert condition.quantity.value == 0  # Failed proposal is retained, never silently corrected.
