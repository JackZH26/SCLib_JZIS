"""Authored end-to-end controls, not original-paper or independent Gold labels."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner import typed_inventory_v2 as typed, wire_v13 as wire
from ingestion.materials_ner import frozen_inventory, typed_inventory_handoff as handoff
from ingestion.materials_ner.contract import canonical, digest, parse_extraction
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import targets
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.sources import save_bundle, sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_quantity_adoption import native
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture(kind='tc_pressure_slope'):
    b, authored, _ = native(kind)
    b.work_id = authored['work_id'] = 'arxiv:authored-native12'
    raw = parse_extraction(authored).model_dump()
    cat = source_catalog(b)
    aliases = {v['block_id']: k for k, v in cat['blocks'].items()}
    def refs(evidence, definition=False):
        out = []
        for e in evidence:
            if e['field'].startswith('/definition') != definition:
                continue
            ids = [k for k, s in cat['spans'].items() if s['block_id'] == e['block_id']]
            field = e['field'][len('/definition'):] if definition else e['field']
            out.append(dict(span_ids=ids, quote=e['quote'], fields=[field]))
        return out
    transport = dict(schema_version=wire.WIRE_VERSION, work_id=b.work_id,
        processed_block_ids=list(cat['blocks']), unread_block_ids=[], limitations=[],
        inventory_dispositions={}, observations=[], additional_items=[], no_result_reason=None,
        context_dispositions=[])
    for key in ('samples', 'states', 'protocols', 'sample_relations', 'condition_supports'):
        transport[key] = [dict(x, evidence=refs(x['evidence'])) for x in raw[key]]
    entries = []
    for index, result in enumerate(raw['results'], 1):
        ids = [k for k, s in cat['spans'].items() if any(e['block_id'] == s['block_id'] for e in result['evidence'])]
        entries.append(dict(type='numeric_result', sample_description=result['sample_id'],
            quantity_description=result['quantity_name_raw'] or result['quantity_kind'],
            quantity_kind=result['quantity_kind'], source_span_ids=ids, context_span_ids=[],
            attribution=dict(origin=result['origin'], source_role=result['source_role'], span_ids=ids),
            value_raw=result['quantity']['raw'], unit=result['quantity']['unit'], unit_span_ids=ids,
            unresolved_reason=None))
        payload = {k: v for k, v in result.items() if k not in {'id', 'sample_id', 'state_id', 'protocol_id', 'definition'}}
        payload['evidence'] = refs(result['evidence'])
        transport['observations'].append(dict(id=result['id'], sample_id=result['sample_id'],
            state_id=result['state_id'], protocol_id=result['protocol_id'], result=payload,
            definition=dict(result['definition'], evidence=refs(result['evidence'], True))))
        transport['inventory_dispositions'][f'I{index}'] = dict(kind='emitted', result_id=result['id'])
    first = dict(schema_version=typed.VERSION, work_id=b.work_id, entries=entries,
        context_assertions=[], span_assessments={s:dict(read=True, non_result_role='context_only',
            reason='Authored regression control.') for s in targets(cat)}, unread_block_ids=[], limitations=[])
    return b, first, transport


@pytest.mark.parametrize('kind', ['tc_pressure_slope', 'electrical_resistivity'])
def test_typed2_to_native12_preserves_full_graph_source_shape_and_positions(kind):
    b, first, raw = fixture(kind)
    jsonschema.validate(first, typed.output_schema(b))
    inventory, _ = typed.project(typed.TypedInventoryV2.model_validate(first), b)
    schema = wire.output_schema(b, inventory)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    projected, proof = wire.AccountedExtraction.model_validate(raw).project(inventory, b)
    result = projected.expand(b)
    checked = validate_extraction(result, b)
    assert checked['valid'], checked['issues']
    assert result.schema_version == 'materials-ner/12'
    assert result.results[-1].quantity.raw == first['entries'][-1]['value_raw']
    assert all(hasattr(e, 'start_char') for entity in result.results for e in entity.evidence)
    assert proof['scientific_assertions_unchanged'] and not proof['scientific_acceptance']
    assert wire.render(b, inventory).index('SOURCE_METADATA') < wire.render(b, inventory).index('FRESH_TYPED_INVENTORY')


def run_fixture(tmp_path, mutation=None):
    b, first, raw = fixture()
    if mutation == 'bad_unit': first['entries'][-1]['unit'] = 'K'
    if mutation == 'bad_quote': raw['observations'][-1]['result']['evidence'][0]['quote'] = 'This does not exist.'
    store = Store(tmp_path / 'queue')
    bundle_hash, _ = save_bundle(store.root, b)
    job = store.enqueue(work_id=b.work_id, bundle_hash=bundle_hash,
        config=configuration(workflow='inventory_v13'), max_attempts=1)
    provider = SequenceProvider([first, raw])
    outcome = run_one(store, job_id=job, provider_override=provider)
    packet = import_packet(store, job)
    return store, provider, outcome, packet


def test_real_worker_path_uses_two_calls_zero_repairs_and_replayable_proposal(tmp_path):
    store, provider, outcome, packet = run_fixture(tmp_path)
    assert outcome['state'] == 'succeeded', outcome
    assert provider.calls == 2
    verify_packet(packet)
    assert packet['receipt']['config']['native_output_schema'] == 'materials-ner/12'
    assert packet['receipt']['training_assessment']['task_feature_assessment']['schema'] == 'materials-ner-task-features/2'
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    db = ProposalDatabase(tmp_path / 'proposals'); db.ingest(packet)
    assert db.summary()['tables']['results'] == len(packet['rows']['results'])


@pytest.mark.parametrize('mutation,expected_calls', [('bad_unit', 1), ('bad_quote', 2)])
def test_invalid_output_is_retained_without_repair_or_admission(tmp_path, mutation, expected_calls):
    _, provider, outcome, packet = run_fixture(tmp_path, mutation)
    assert outcome['state'] == 'quarantined', outcome
    assert provider.calls == expected_calls
    verify_packet(packet)
    assert packet['rows']['results'] == []


@pytest.mark.parametrize('mutation', ['first_raw', 'projection', 'native_quantity', 'first_policy'])
def test_tampered_self_contained_receipts_do_not_pass_replay(tmp_path, mutation):
    _, _, _, packet = run_fixture(tmp_path)
    if mutation == 'first_raw': packet['receipt']['inventory_reads'][0]['raw_output'] += ' '
    if mutation == 'projection': packet['receipt']['inventory_reads'][0]['link_projection']['scientific_acceptance'] = True
    if mutation == 'native_quantity': packet['receipt']['extraction']['results'][-1]['quantity']['value'] = 99
    if mutation == 'first_policy': packet['receipt']['config']['inventory_schema_sha256'] = '0' * 64
    packet['run_id'] = digest(packet['receipt'])
    packet['packet_hash'] = digest({k:v for k,v in packet.items() if k != 'packet_hash'})
    with pytest.raises(ValueError): verify_packet(packet)


@pytest.mark.parametrize('quote', ['not in source', 'A'])
def test_missing_or_repeated_literal_cannot_select_an_occurrence(quote):
    b, _, _ = fixture()
    cat = source_catalog(b)
    ref = wire.EvidenceReference(span_ids=list(cat['spans']), quote=quote, fields=['/sample_id'])
    with pytest.raises(ValueError, match='literal_witness_missing_or_ambiguous'):
        wire.resolve_reference(ref, cat)


def test_new_workflow_is_opt_in_and_never_requests_automatic_repair():
    old, new = configuration(), configuration(workflow='inventory_v13')
    assert old['workflow'] == 'single_pass_v1' and 'image_inputs' not in old
    assert old['registry_version'] != new['registry_version']
    assert new['max_inventory_repairs'] == new['max_extraction_repairs'] == new['max_evidence_patches'] == 0


def test_typed2_handoff_is_explicit_and_legacy_discriminator_cannot_relabel_it():
    b, first, _ = fixture()
    model = typed.TypedInventoryV2.model_validate(first); inventory, proof = typed.project(model, b)
    captures = dict(source_bundle=canonical(b.model_dump()), source_catalog=canonical(source_catalog(b)),
        prompt=typed.render(b), frozen_schema=canonical(typed.output_schema(b)), raw_output=canonical(first),
        typed_inventory=canonical(model.model_dump()), inventory=canonical(inventory.model_dump()),
        validation=canonical(proof['validation']), projection=canonical(proof), layout='null')
    receipt = dict(schema='materials-typed-source-inventory-attempt/2', work_id=b.work_id, terminal=True,
        provider_calls=1, status='typed_inventory_valid', source_unchanged=True, scientific_acceptance=False,
        full_graph_extraction=False, item_count=len(inventory.items),
        **{k:dict(path='/authored/'+k,sha256=sha(v.encode())) for k,v in captures.items()})
    snapshot = handoff.build(b, receipt_raw=canonical(receipt), captures=captures)
    assert frozen_inventory.verify(snapshot) == inventory
    receipt['schema'] = 'materials-typed-source-inventory-attempt/1'
    with pytest.raises(ValueError): handoff.build(b, receipt_raw=canonical(receipt), captures=captures)
