"""Original-source coordinates, table joins and the real durable worker.

Selections and provider responses in these tests are authored regression inputs,
never independent Gold or new model results. All 70 inventory items remain in
the real-source test denominator, including its 58 required table occurrences.
"""
from copy import deepcopy
from functools import lru_cache
import re

import jsonschema
import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner import source_atoms as atoms, source_atom_stages as stages
from ingestion.materials_ner import condition_catalog_stages as bridge, frozen_inventory, item_worker
from ingestion.materials_ner.contract import canonical, digest, Quantity
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import resolve_quote
from ingestion.materials_ner.worker import run_one
from test_materials_ner_compiled_catalog import selected
from test_materials_ner_frozen_inventory import inputs
from test_materials_ner_item_stages import StageProvider


@lru_cache(maxsize=1)
def _source():
    bundle, inventory, original, old = selected()
    ledger = private_json('materials_ner_table_ownership_ledger.json')['cells']
    _, _, receipt, captures, _ = inputs(bundle, inventory)
    occurrences = []
    for cell in ledger:
        raw = cell['source_cell']; text = re.sub(r'(?:\\footnotemark\[[1-9][0-9]*\])+$', '', raw['quote'])
        occurrences.append(dict(id=cell['id'], block_id=raw['block_id'], start_char=raw['start_char'],
            end_char=raw['start_char']+len(text), quote=text, quote_sha256=sha(text.encode())))
    parent = frozen_inventory.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=occurrences)
    context = atoms.context(bundle, parent, ledger, marker_convention='numeric_to_lower_alpha')
    adapter = stages.Adapter(context); catalog = atoms.candidates(bundle, adapter.ownership(bundle))

    def convert(value):
        if isinstance(value, dict):
            if set(value) == {'candidate_id', 'literal'}:
                original_clause = original['texts'][value['candidate_id']]
                if value['literal'] is None:
                    return dict(candidate_id=value['candidate_id'], end_candidate_id=None)
                a, b = resolve_quote(original_clause['quote'], value['literal'])
                a += original_clause['start_char']; b += original_clause['start_char']
                # Regression author selects enclosing printed tokens. Extra
                # punctuation stays original source text, never stripped output.
                choices = [(key, row) for key, row in catalog['texts'].items()
                           if row['clause_id'] == value['candidate_id']]
                exact = [(k, r) for k, r in choices if r['start_char'] == a and r['end_char'] == b]
                if exact:
                    return dict(candidate_id=exact[0][0], end_candidate_id=None)
                first = min([(k, r) for k, r in choices if r['start_char'] <= a and r['end_char'] > a],
                    key=lambda x:(-x[1]['start_char'], x[1]['end_char']-x[1]['start_char']))
                last = min([(k, r) for k, r in choices if r['start_char'] < b and r['end_char'] >= b],
                    key=lambda x:(x[1]['end_char'], x[1]['end_char']-x[1]['start_char']))
                return dict(candidate_id=first[0], end_candidate_id=last[0])
            return {key: convert(child) for key, child in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        return value

    choices = convert(old); choices['schema_version'] = atoms.POLICY
    for sample in choices['samples']:
        for state in sample['states']:
            state['table_cell_ids'] = []
    # One source row/column for the emitted regression result, not all 58 cells.
    choices['samples'][0]['states'][0]['table_cell_ids'] = ['T1:R1:C2']
    return bundle, inventory, parent, context, catalog, choices


def source():
    return deepcopy(_source())


def typed():
    bundle, inventory, parent, context, candidates, raw = source()
    adapter = stages.Adapter(context); choices = atoms.CatalogChoices.model_validate(raw)
    declared = adapter.check_declarations(choices, inventory, bundle, 128)
    rel = stages.frozen.Relations(schema_version='materials-source-catalog-relations/1', work_id=bundle.work_id,
        protocol_uses={p.id: dict(resolution='none', uses=[], explanation='Authored regression: no method-condition relation proposed.')
                       for p in declared.protocols}, sample_relations=[])
    catalog, proof = adapter.project(choices, rel, bundle)
    mapping = atoms.verify_context(context, bundle, inventory)[1]
    first = next(k for k, v in mapping.items() if v == 'T1:R1:C2')
    owners = {item.id: dict(resolution='unresolved', explanation='Authored regression leaves this result unresolved.',
        source_span_ids=item.source_span_ids, attribution=dict(source_role='unknown', cited_source_raw=None, source_span_ids=item.source_span_ids))
        for item in inventory.items}
    owners[first] = dict(resolution='bound', sample_id='sample:1', state_id='state:1:1', protocol_id='protocol:1',
        source_span_ids=next(i.source_span_ids for i in inventory.items if i.id == first),
        attribution=dict(source_role='primary', cited_source_raw=None,
            source_span_ids=next(i.source_span_ids for i in inventory.items if i.id == first)))
    selection = stages.frozen.OwnerBindings(schema_version=stages.BINDING_VERSION, work_id=bundle.work_id,
        catalog_sha256=digest(catalog.model_dump()), decisions=owners)
    return bundle, inventory, parent, context, candidates, choices, adapter, rel, catalog, proof, selection, first


def test_exact_positions_copy_original_tex_and_preserve_ner10_conditions():
    bundle, inventory, _, _, _, choices, adapter, rel, catalog, proof, selection, _ = typed()
    jsonschema.validate(choices.model_dump(), adapter.declaration_schema(bundle, inventory))
    projection = proof['source_atom_projection']
    assert projection['graph']['states'][0]['conditions'][0]['kind'] == 'reported_magnetic_field'
    assert projection['graph']['states'][0]['conditions'][0]['quantity']['value'] == 1.0
    assert projection['graph']['states'][0]['conditions'][0]['quantity']['unit'] == 'mT'
    window = projection['graph']['states'][0]['conditions'][1]
    assert window['role'] == 'study_extent' and window['quantity']['relation'] == 'interval'
    assert (window['quantity']['lower'], window['quantity']['upper']) == (1.75, 100.0)
    assert projection['graph']['samples'][0]['isotopes'][0]['fraction']['status'] == 'not_reported'
    assert projection['graph']['samples'][1]['isotopes'][0]['fraction']['value'] == 80
    owned, plan, binding = adapter.bind(selection, choices, rel, inventory, bundle)
    graph, _, _ = bridge.assemble(bundle, inventory, catalog, {}, None, missing_item_ids=[i.id for i in inventory.items])
    expanded = graph.expand(bundle)
    for key in ('samples', 'states', 'protocols'):
        assert [o.model_dump() for o in getattr(expanded, key)] == projection['graph'][key]
    assert expanded.schema_version == 'materials-ner/10'
    assert len(binding['table_owner_checks']) == 58
    assert not plan['scientific_acceptance']
    assert bridge.body(owned).schema_version == 'materials-source-declarations/3'


@pytest.mark.parametrize('mutation', ['foreign', 'old_literal', 'cross_clause', 'reversed'])
def test_no_retyped_phrases_or_disconnected_endpoint_ranges(mutation):
    bundle, _, _, context, candidates, raw = source()
    if mutation == 'old_literal':
        raw['samples'][0]['form']['literal'] = 'Invented form'
        with pytest.raises(ValueError):
            atoms.CatalogChoices.model_validate(raw)
        return
    ids = [(key, row) for key, row in candidates['texts'].items() if key.startswith('A')]
    first, second = ids[0], ids[1]
    choice = dict(candidate_id=first[0], end_candidate_id=None)
    if mutation == 'foreign': choice['candidate_id'] = 'A999999'
    elif mutation == 'cross_clause': choice['end_candidate_id'] = next(k for k, r in ids if r['clause_id'] != first[1]['clause_id'])
    else: choice = dict(candidate_id=second[0], end_candidate_id=first[0])
    with pytest.raises(ValueError, match='staged_atom_'):
        atoms.select(candidates, atoms.TextChoice.model_validate(choice), bundle)


@pytest.mark.parametrize('mutation', ['row', 'note', 'mixed_rows', 'duplicate_owner', 'unassigned_cell', 'wrong_state'])
def test_table_cell_cannot_borrow_another_row_note_or_frozen_owner(mutation):
    bundle, inventory, _, context, candidates, choices, adapter, rel, catalog, _, selection, first = typed()
    raw = choices.model_dump()
    if mutation in {'unassigned_cell', 'wrong_state'}:
        data = selection.model_dump()
        if mutation == 'wrong_state': data['decisions'][first].update(sample_id='sample:2', state_id='state:2:1')
        else:
            mapping = atoms.verify_context(context, bundle, inventory)[1]
            key = next(k for k, v in mapping.items() if v == 'T1:R13:C3')
            data['decisions'][key] = deepcopy(data['decisions'][first])
            data['decisions'][key]['source_span_ids'] = next(i.source_span_ids for i in inventory.items if i.id == key)
            data['decisions'][key]['attribution']['source_span_ids'] = data['decisions'][key]['source_span_ids']
        with pytest.raises(ValueError, match='result_table_owner_mismatch'):
            adapter.bind(stages.frozen.OwnerBindings.model_validate(data), choices, rel, inventory, bundle)
        return
    state = raw['samples'][0]['states'][0]
    if mutation == 'row': state['sample_support'] = dict(candidate_id='T1:R14:C2/source_row', end_candidate_id=None)
    elif mutation == 'note': state['preparation'] = dict(candidate_id='T1:R13:C3/note_c', end_candidate_id=None)
    elif mutation == 'mixed_rows': state['table_cell_ids'].append('T1:R14:C2')
    else: raw['samples'][1]['states'][0]['table_cell_ids'] = ['T1:R1:C2']
    with pytest.raises(ValueError, match='staged_atom_'):
        adapter.check_declarations(atoms.CatalogChoices.model_validate(raw), inventory, bundle, 128)


@pytest.mark.parametrize('mutation', ['bundle', 'cell', 'occurrence', 'inventory', 'parent'])
def test_frozen_context_is_source_and_parent_bound(mutation):
    bundle, inventory, parent, context, _, _ = source()
    if mutation == 'bundle': context['bundle_sha256'] = '0'*64
    elif mutation == 'cell': context['ledger'][0]['source_cell']['start_char'] += 1
    elif mutation == 'occurrence': context['required_occurrences'][0]['end_char'] -= 1
    elif mutation == 'inventory': context['inventory_sha256'] = '0'*64
    else: context['parent_run_id'] = 'another-parent'
    with pytest.raises(ValueError):
        atoms.verify_context(context, bundle, inventory, parent)


def responses():
    bundle, inventory, parent, context, _, choices, adapter, rel, catalog, _, selection, first = typed()
    decisions = {i.id: dict(decision='held', reason='unresolved', explanation='Authored regression intentionally leaves this result unresolved.') for i in inventory.items}
    item = next(i for i in inventory.items if i.id == first)
    spans = list(dict.fromkeys(item.source_span_ids+item.context_span_ids))
    quantity = Quantity(status='reported', raw='91.19(5)', relation='exact', value=91.19, unit='K',
        uncertainty=dict(kind='reported_unspecified', minus=0.05, plus=0.05, raw='(5)')).model_dump()
    observation = dict(sample_id='sample:1', state_id='state:1:1', protocol_id='protocol:1',
        definition=dict(criterion='unspecified', criterion_raw=None, parameters=[], evidence=[]),
        result=dict(quantity_kind='tc', quantity_name_raw=r'$^{16}T_c$', quantity=quantity, origin='observed', source_role='primary',
            component_raw=None, interpretation_raw=None, cited_source_raw=None, dependencies=[], qualifiers=[],
            evidence=[dict(fields=['/sample_id','/state_id','/protocol_id','/quantity','/quantity_kind','/quantity_name_raw','/origin','/source_role'], span_ids=spans)]))
    decisions[first] = dict(decision='emitted', observation=observation)
    links = dict(schema_version='materials-source-context-links/1', work_id=bundle.work_id, condition_supports=[],
        contexts={c.id: dict(resolution='unresolved', bindings=[], explanation='Authored regression retains context for independent review.') for c in inventory.context_assertions})
    ids = [i.id for i in inventory.items]
    outputs = [choices.model_dump(), rel.model_dump(), selection.model_dump(), *[
        dict(schema_version='materials-source-item-group/1', work_id=bundle.work_id, decisions={key: decisions[key] for key in ids[n:n+4]})
        for n in range(0,len(ids),4)], links]
    return bundle, inventory, parent, context, outputs, first


def test_durable_worker_replays_exact_source_and_every_unresolved_occurrence(tmp_path):
    bundle, inventory, parent, context, outputs, first = responses()
    store = Store(tmp_path/'atoms'); job = item_worker.enqueue(store, parent, workflow=stages.WORKFLOW,
        field_generation_policy=stages.POLICY, source_atom_context=context, max_source_items=128,
        max_input_tokens=120000, timeout_seconds=600)
    result = run_one(store, job_id=job, provider_override=StageProvider(outputs))
    assert result['state'] == 'quarantined', result
    packet = import_packet(store, job); verify_packet(packet)
    receipt = packet['receipt']; assert not receipt['staged_errors']
    assert receipt['extraction']['schema_version'] == 'materials-ner/10'
    assert len(receipt['extraction']['results']) == 1
    assert receipt['extraction']['results'][0]['id'] == 'item:'+first
    assert receipt['frozen_source_accounting']['source_cells'] == 58
    assert receipt['frozen_source_accounting']['materialized_cells'] == 1
    assert len(receipt['staged_assembly']['source_item_ids']) == 70
    assert receipt['staged_assembly']['frozen_owner_projection']['table_owner_checks'][0]['source_structure_verified']
    db = ProposalDatabase(tmp_path/'proposals'); assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    from ingestion.materials_ner.staged_revision import resolve_parent
    assert resolve_parent(packet)[0].expand(bundle).model_dump() == receipt['extraction']
    bad = deepcopy(receipt); bad['config']['source_atom_context']['ledger'][0]['source_cell']['quote'] = 'forged'
    with pytest.raises(ValueError, match='context_hash_mismatch'):
        item_worker.verify_receipt(bad, bundle, packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_old_workflow_cannot_silently_select_new_transport():
    _, _, parent, context, _, _ = source()
    with pytest.raises(ValueError, match='context_policy_mismatch'):
        item_worker.configuration(parent, workflow='source_item_stages_v3', field_generation_policy=stages.POLICY, source_atom_context=context)
    with pytest.raises(ValueError, match='context_required'):
        item_worker.configuration(parent, workflow=stages.WORKFLOW, field_generation_policy=stages.POLICY)


def test_method_links_and_exact_quote_evidence_survive_native10_expansion():
    bundle, inventory, _, _, _, choices, adapter, rel, _, _, _, _ = typed()
    data = rel.model_dump()
    data['protocol_uses']['protocol:1'] = dict(resolution='linked', explanation=None,
        uses=[dict(state_id='state:1:1', condition_id='condition:1:1:1', source_span_ids=['S13'])])
    catalog, _ = adapter.project(choices, stages.frozen.Relations.model_validate(data), bundle)
    graph, _, _ = bridge.assemble(bundle, inventory, catalog, {}, None, missing_item_ids=[i.id for i in inventory.items])
    expanded = graph.expand(bundle)
    assert expanded.protocols[0].context_uses[0].model_dump() == dict(state_id='state:1:1', condition_id='condition:1:1:1')
    assert graph.states[0].evidence[0].exact_quotes
    assert expanded.states[0].evidence[0].quote == graph.states[0].evidence[0].exact_quotes[0].quote


def test_compact_prompt_keeps_science_and_owner_schema_enforces_table_ids():
    bundle, inventory, _, _, _, choices, adapter, _, catalog, _, selection, first = typed()
    raw = catalog.model_dump(); compact = stages.prompt_view(raw)
    for name in ('samples', 'states', 'protocols'):
        for before, after in zip(raw[name], compact[name], strict=True):
            assert {k:v for k,v in before.items() if k != 'evidence'} == {k:v for k,v in after.items() if k != 'evidence'}
            for old, new in zip(before['evidence'], after['evidence'], strict=True):
                assert {k:v for k,v in old.items() if k != 'exact_quotes'} == new
    schema = adapter.binding_schema(bundle, inventory, catalog, declarations=choices)
    jsonschema.validate(selection.model_dump(), schema)
    wrong = selection.model_dump(); wrong['decisions'][first].update(sample_id='sample:2', state_id='state:2:1')
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(wrong, schema)
    assert len(canonical(schema)) < 20000
    assert raw == catalog.model_dump()
