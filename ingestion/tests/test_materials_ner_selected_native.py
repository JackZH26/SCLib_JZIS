"""Authored controls for source selection, replay and a non-promoting preview."""
from copy import deepcopy

import jsonschema
import pytest

from ingestion.materials_ner import typed_inventory_v3 as typed, wire_v14 as wire
from ingestion.materials_ner import canonical_preview
from ingestion.materials_ner.contract import parse_extraction
from ingestion.materials_ner.sources import save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import configuration, run_one
from ingestion.materials_ner.proposals import import_packet, verify_packet
from test_materials_ner_native12_workflow import fixture as old_fixture
from test_materials_ner_inventory_v2 import SequenceProvider


def fixture(kind='tc_pressure_slope'):
    bundle, old, transport = old_fixture(kind)
    for document in bundle.documents:
        document.source_kind = "original_pdf"
    cat = typed.catalog(bundle)
    first = deepcopy(old); first['schema_version'] = typed.VERSION
    for item in first['entries']:
        raw = item.pop('value_raw')
        for key in ('unit', 'unit_span_ids', 'source_span_ids'):
            item.pop(key)
        matches = [k for k, v in cat['numeric_catalog']['numeric_candidates'].items()
                   if v['selectable'] and v['quote'].strip() == raw.strip()]
        assert matches, (raw, cat['numeric_catalog']['numeric_candidates'])
        item['numeric_candidate_id'] = matches[0]
    def rewrite(value):
        if isinstance(value, list):
            return [rewrite(x) for x in value]
        if isinstance(value, dict):
            if set(value) == {'span_ids', 'quote', 'fields'}:
                keys = [k for k, v in cat['witness_selections'].items() if value['quote'] in v['quote']]
                assert keys, value
                key = min(keys, key=lambda k: len(cat['witness_selections'][k]['quote']))
                return dict(selection_id=key, quote=value['quote'], fields=value['fields'])
            return {k: rewrite(v) for k, v in value.items()}
        return value
    transport = rewrite(transport); transport['schema_version'] = wire.WIRE_VERSION
    return bundle, first, transport


@pytest.mark.parametrize('kind', ['tc_pressure_slope', 'electrical_resistivity'])
def test_source_selection_compiles_full_numeric_shape_and_graph(kind):
    b, first, raw = fixture(kind)
    jsonschema.validate(first, typed.output_schema(b))
    model = typed.TypedInventory.model_validate(first)
    inv, proof = typed.project(model, b)
    entry = proof['compiled_inventory']['entries'][-1]
    candidate = typed.catalog(b)['numeric_catalog']['numeric_candidates'][first['entries'][-1]['numeric_candidate_id']]
    assert entry['value_raw'] == candidate['quote']
    assert entry['unit'] == candidate['unit_raw']
    schema = wire.output_schema(b, inv)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(raw, schema)
    compact, _ = wire.AccountedExtraction.model_validate(raw).project(inv, b)
    graph = compact.expand(b)
    assert graph.schema_version == 'materials-ner/12'
    assert graph.results[-1].quantity.raw == entry['value_raw']
    assert not proof['scientific_acceptance']


def run_fixture(tmp_path, mutation=None):
    b, first, raw = fixture()
    if mutation == 'wrong_kind':
        first['entries'][-1]['quantity_kind'] = 'tc'
    if mutation == 'unknown_quote':
        raw['observations'][-1]['result']['evidence'][0]['quote'] = 'This is absent from the source.'
    store = Store(tmp_path/'queue'); hashed, _ = save_bundle(store.root, b)
    job = store.enqueue(work_id=b.work_id, bundle_hash=hashed,
        config=configuration(workflow='inventory_v14'), max_attempts=1)
    provider = SequenceProvider([first, raw]); outcome = run_one(store, job_id=job, provider_override=provider)
    packet = import_packet(store, job); verify_packet(packet)
    return provider, outcome, packet


def test_worker_and_preview_are_replayable_and_never_promote(tmp_path):
    provider, outcome, packet = run_fixture(tmp_path)
    assert provider.calls == 2
    assert outcome['state'] == 'succeeded', outcome
    preview = canonical_preview.build(packet)
    assert canonical_preview.retained_graph(preview, packet) == packet['receipt']['extraction']
    mapped = [r for r in preview['results'] if r['candidate_fields']]
    assert mapped
    for row in mapped:
        assert not row['ready_to_insert']
        assert row['candidate_fields']['raw']['source_quantity']['quantity']['raw']
        assert row['candidate_fields']['uncertainty'] == {}
        assert row['normalized_readout']['uncertainty']['minus'] > 0
        assert 'physical_event_identity_required' in row['holds']
    assert not preview['scientific_acceptance'] and not preview['database_writes']
    changed = deepcopy(preview); changed['results'][-1]['holds'] = []
    with pytest.raises(ValueError, match='preview_mismatch'):
        canonical_preview.verify(changed, packet)


@pytest.mark.parametrize('mutation,calls', [('wrong_kind', 1), ('unknown_quote', 2)])
def test_failed_selections_are_retained_without_repair(tmp_path, mutation, calls):
    provider, outcome, packet = run_fixture(tmp_path, mutation)
    assert provider.calls == calls
    assert outcome['state'] == 'quarantined', outcome
    assert not packet['rows']['results']
    assert canonical_preview.build(packet)['no_result_graph']


def test_coordinate_selection_does_not_merge_repeated_source_occurrences():
    cat = dict(witness_selections=dict(T1=dict(block_id='b', start_char=0, quote='2 K; 2 K', end_char=8),
        N1=dict(block_id='b', start_char=0, quote='2 K', end_char=3),
        N2=dict(block_id='b', start_char=5, quote='2 K', end_char=8)))
    def ref(key, quote=None):
        return wire.EvidenceReference(selection_id=key, quote=quote, fields=['/quantity'])
    assert wire.resolve_reference(ref('N1'), cat)[0]['start_char'] == 0
    assert wire.resolve_reference(ref('N2'), cat)[0]['start_char'] == 5
    with pytest.raises(ValueError, match='ambiguous'):
        wire.resolve_reference(ref('T1', '2 K'), cat)


@pytest.mark.parametrize('mutation', ['raw', 'projection', 'source_selection'])
def test_replay_rejects_tampered_selected_first_read(tmp_path, mutation):
    _, _, packet = run_fixture(tmp_path)
    broken = deepcopy(packet)
    if mutation == 'raw':
        broken['receipt']['inventory_reads'][0]['raw_output'] += ' '
    elif mutation == 'projection':
        broken['receipt']['inventory_reads'][0]['link_projection']['selections'][0]['location']['quote'] = 'fake'
    else:
        broken['receipt']['typed_inventory']['entries'][0]['numeric_candidate_id'] = 'N404'
    with pytest.raises(ValueError):
        verify_packet(broken)


def test_unknown_numeric_selection_is_rejected_before_projection():
    b, first, _ = fixture()
    first['entries'][-1]['numeric_candidate_id'] = 'N404'
    checked = typed.inspect(typed.TypedInventory.model_validate(first), b)
    assert not checked['valid']
    assert checked['issues'][0]['code'] == 'selected_inventory_numeric_not_selectable'


def test_unvalued_statement_is_copied_without_retyping_and_context_source_is_rejected():
    b, first, _ = fixture()
    cat = typed.catalog(b)
    key, row = next((k, v) for k, v in cat['texts'].items() if v['target'] and v['selectable'])
    first['entries'] = [dict(type='unvalued_result', sample_description='Authored specimen',
        quantity_description='Authored qualitative assertion', quantity_kind='tc', statement_text_id=key,
        context_span_ids=[], attribution=dict(origin='unknown', source_role='unknown', span_ids=[]),
        value_status='qualitative', unresolved_reason='No separate numeric result selected in this authored control.')]
    model = typed.TypedInventory.model_validate(first)
    compiled, selections = typed.compile_selection(model, b)
    assert compiled.entries[0].statement_raw == row['quote']
    assert selections[0]['location']['quote'] == row['quote']
    assert 'statement_raw' not in model.model_dump()['entries'][0]
    first['entries'][0]['statement_text_id'] = 'T404'
    assert not typed.inspect(typed.TypedInventory.model_validate(first), b)['valid']
