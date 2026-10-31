"""Standalone-call provenance, original-cell closure and durable stage replay.

Synthetic fixture receipts below are test inputs, not scientific reference data.
"""
from copy import deepcopy
import json

import pytest

from ingestion.materials_ner import frozen_inventory as frozen, item_worker, item_stages
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import Inventory, output_schema, validate_inventory
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_item_stages import fixture, StageProvider, responses


def inputs(bundle=None, inventory=None):
    if bundle is None:
        bundle, inventory, *_ = fixture()
    captures = dict(source_bundle=canonical(bundle.model_dump()),
        source_catalog=canonical(source_catalog(bundle)),
        prompt='Synthetic inventory prompt; this is not an actual provider invocation.',
        frozen_schema=canonical(output_schema(bundle)), raw_output=canonical(inventory.model_dump()),
        inventory=canonical(inventory.model_dump()), validation=canonical(validate_inventory(inventory, bundle)))
    receipt = dict(schema='materials-full-source-inventory-attempt/1', work_id=bundle.work_id,
        terminal=True, provider_calls=1, status='inventory_valid', source_unchanged=True,
        scientific_acceptance=False, full_graph_extraction=False, item_count=len(inventory.items),
        model='synthetic-fixture', response_id='synthetic-only',
        **{key: dict(path=f'/synthetic-only/{key}.json', sha256=sha(raw.encode())) for key, raw in captures.items()})
    item = next(i for i in inventory.items if i.value_raw is not None)
    block = next(b for b in bundle.blocks if item.value_raw in b.text)
    start = block.text.index(item.value_raw)
    occurrence = dict(id='T1:R1:C1', block_id=block.id, start_char=start,
        end_char=start+len(item.value_raw), quote=item.value_raw, quote_sha256=sha(item.value_raw.encode()))
    return bundle, inventory, receipt, captures, [occurrence]


def snapshot():
    bundle, inventory, receipt, captures, occurrences = inputs()
    parent = frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures,
        required_occurrences=occurrences)
    return bundle, inventory, parent


def test_original_standalone_receipt_and_model_bytes_survive_handoff():
    bundle, inventory, parent = snapshot()
    assert frozen.verify(parent) == inventory
    assert item_worker.verify_parent(parent, bundle) == inventory
    assert parent['new_model_calls'] == 0
    assert parent['source_accounting']['source_cells'] == 1
    assert not parent['source_accounting']['full_source_coverage_established']
    assert parent['captures']['raw_output'] == canonical(inventory.model_dump())


@pytest.mark.parametrize('key', frozen.CAPTURE_KEYS)
def test_original_input_output_or_validation_hash_drift_is_rejected(key):
    bundle, _, receipt, captures, occurrences = inputs()
    captures[key] += '\n'
    with pytest.raises(ValueError, match='capture_hash_mismatch'):
        frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=occurrences)


@pytest.mark.parametrize('change', ['value', 'source', 'cell_offset', 'cell_hash', 'approval', 'proof', 'count'])
def test_rehashing_a_tampered_snapshot_does_not_bypass_replay(change):
    _, _, parent = snapshot()
    if change == 'value': parent['inventory']['items'][0]['value_raw'] = '999 K'
    if change == 'source': parent['bundle']['blocks'][0]['text'] += ' Invented source.'
    if change == 'cell_offset': parent['required_occurrences'][0]['start_char'] += 1
    if change == 'cell_hash': parent['required_occurrences'][0]['quote_sha256'] = '0'*64
    if change == 'approval': parent['scientific_acceptance'] = True
    if change == 'proof': parent['source_accounting']['rows'][0]['inventory_item_id'] = 'I999'
    if change == 'count': parent['new_model_calls'] = 1
    parent['run_id'] = digest({k: v for k, v in parent.items() if k != 'run_id'})
    with pytest.raises(ValueError): frozen.verify(parent)


def test_same_source_version_metadata_can_advance_without_rewriting_old_inputs():
    bundle, _, receipt, captures, occurrences = inputs()
    original = captures['source_bundle']
    bundle.documents[0].publication_version = 'v2'
    bundle.documents[0].version_status = 'verified'
    bundle.acquisition_notes += ['Synthetic version identity evidence for this test.']
    parent = frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=occurrences)
    frozen.verify(parent)
    assert parent['captures']['source_bundle'] == original
    changed = bundle.model_copy(deep=True)
    changed.documents[0].coverage = 'abstract_only'
    with pytest.raises(ValueError, match='source_changed'):
        frozen.build(changed, receipt_raw=canonical(receipt), captures=captures, required_occurrences=occurrences)


@pytest.mark.parametrize('mode', ['missing_item', 'duplicate_value', 'duplicate_cell', 'wrong_occurrence'])
def test_source_cell_gate_detects_omissions_ambiguity_and_duplicate_counts(mode):
    bundle, inventory, _, _, occurrences = inputs()
    selected = frozen.occurrence_accounting(bundle, inventory, occurrences)['rows'][0]['inventory_item_id']
    if mode == 'missing_item': inventory.items = [i for i in inventory.items if i.id != selected]
    if mode == 'duplicate_value':
        item = next(i for i in inventory.items if i.id == selected)
        inventory.items.append(item.model_copy(update={'id': 'I99'}))
    if mode == 'duplicate_cell': occurrences.append(dict(occurrences[0], id='T1:R2:C1'))
    if mode == 'wrong_occurrence':
        # The same literal elsewhere is not covered by the item's primary spans.
        item = next(i for i in inventory.items if i.id == selected)
        item.source_span_ids = [s for s in source_catalog(bundle)['spans'] if s not in item.source_span_ids][:1]
        if not item.source_span_ids: item.value_raw = 'unrelated literal'
    with pytest.raises(ValueError): frozen.occurrence_accounting(bundle, inventory, occurrences)


def test_retained_inventory_must_be_the_actual_model_output():
    bundle, inventory, receipt, captures, occurrences = inputs()
    changed = inventory.model_copy(deep=True)
    changed.items[0].sample_raw = 'A rewritten subject'
    captures['inventory'] = canonical(changed.model_dump())
    receipt['inventory']['sha256'] = sha(captures['inventory'].encode())
    with pytest.raises(ValueError, match='output_was_rewritten'):
        frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=occurrences)


def test_explicit_budget_supports_seventy_items_without_silent_truncation():
    bundle, inventory, _, _, _ = inputs()
    source_item = next(i for i in inventory.items if i.value_raw is not None)
    inventory.items = [source_item.model_copy(update={'id': f'I{i}'}) for i in range(70)]
    for span in inventory.span_dispositions:
        span.item_ids = [i.id for i in inventory.items if span.span_id in i.source_span_ids]
        span.role = 'result_assertions' if span.item_ids else 'context_only'
        span.reason = None if span.item_ids else 'No result selected for this synthetic budget test.'
    bundle, inventory, receipt, captures, _ = inputs(bundle, inventory)
    parent = frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=[])
    assert item_worker.configuration(parent, max_source_items=96)['max_source_items'] == 96
    with pytest.raises(ValueError, match='exceeds_declared_budget'):
        item_worker.configuration(parent, max_source_items=64)
    with pytest.raises(ValueError, match='budget_invalid'):
        item_worker.configuration(parent, max_source_items=129)


@pytest.mark.parametrize('fail_at', [None, 1, 3])
def test_real_worker_path_reuses_inventory_without_a_new_inventory_call(tmp_path, fail_at):
    bundle, inventory, _, catalog, decisions, links = fixture()
    _, _, receipt, captures, occurrences = inputs(bundle, inventory)
    parent = frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=occurrences)
    store = Store(tmp_path/'staged')
    job = item_worker.enqueue(store, parent, group_size=2)
    assert item_worker.enqueue(store, parent, group_size=2) == job
    provider = StageProvider(responses(bundle, catalog, decisions, links), fail_at=fail_at)
    result = run_one(store, job_id=job, provider_override=provider)
    assert result['state'] == ('failed' if fail_at else 'succeeded')
    packet = import_packet(store, job)
    verify_packet(packet)
    assert packet['receipt']['stages'][0]['name'] == 'catalog'
    assert all(s['name'] != 'inventory' for s in packet['receipt']['stages'])
    accounting = packet['receipt']['frozen_source_accounting']
    assert accounting['source_cells'] == 1
    assert accounting['materialized_cells'] == (0 if fail_at == 1 else 1)
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    database = ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as db: assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    changed = deepcopy(packet['receipt'])
    changed['frozen_source_accounting']['source_cells'] = 0
    with pytest.raises(ValueError, match='frozen_occurrence_receipt_mismatch'):
        item_worker.verify_receipt(changed, bundle, packet['raw_output'])
    changed = deepcopy(packet['receipt'])
    del changed['config']['frozen_inventory_snapshot_version']
    with pytest.raises(ValueError, match='frozen_parent_policy_mismatch'):
        item_worker.verify_receipt(changed, bundle, packet['raw_output'])


def test_cell_outcome_cannot_pass_on_wrong_number_or_a_planned_reference():
    _, _, parent = snapshot()
    item = parent['source_accounting']['rows'][0]['inventory_item_id']
    assert not frozen.outcome_accounting(parent, {})['fully_materialized']
    report = {'extraction': {'results': [{'id': item_stages.result_id(item), 'quantity': {'raw': '999 K'}}]}}
    assert frozen.outcome_accounting(parent, report)['rows'][0]['status'] == 'source_value_changed'
    report['extraction']['results'][0]['quantity']['raw'] = parent['required_occurrences'][0]['quote']
    assert frozen.outcome_accounting(parent, report)['fully_materialized']


def test_existing_result_compiler_is_stable_under_decision_order():
    _, _, _, catalog, decisions, _ = fixture()
    typed_catalog = item_stages.EntityCatalog.model_validate(catalog)
    group = item_stages.ItemGroup(schema_version='materials-source-item-group/1',
        work_id=catalog['work_id'], decisions=decisions)
    forward = item_stages.graph_objects(typed_catalog, group.decisions)
    reverse = item_stages.graph_objects(typed_catalog, dict(reversed(list(group.decisions.items()))))
    index = lambda graph: {o['inventory_item_ids'][0]: o['id'] for o in graph['observations']}
    assert index(forward) == index(reverse)


def test_duplicate_json_keys_are_not_silently_accepted():
    with pytest.raises(ValueError, match='duplicate_json_key'):
        frozen.parse('{"items":[],"items":[1]}')


def test_public_cli_freezes_and_enqueues_without_invoking_a_model(tmp_path, capsys):
    from ingestion.materials_ner.cli import main
    bundle, _, receipt, captures, occurrences = inputs()
    for key, raw in captures.items():
        path = tmp_path/f'{key}.json'
        path.write_bytes(raw.encode())
        receipt[key]['path'] = str(path)
    receipt_path = tmp_path/'receipt.json'
    receipt_path.write_text(canonical(receipt))
    occurrence_path = tmp_path/'occurrences.json'
    occurrence_path.write_text(canonical(occurrences))
    out = tmp_path/'frozen.json'
    root = tmp_path/'queue'
    assert main(['--root', str(root), 'freeze-inventory', '--bundle', receipt['source_bundle']['path'],
        '--source-receipt', str(receipt_path), '--source-occurrences', str(occurrence_path), '--out', str(out)]) == 0
    assert json.loads(capsys.readouterr().out)['new_model_calls'] == 0
    frozen.verify(json.loads(out.read_bytes()))
    assert main(['--root', str(root), 'stage-enqueue', '--parent-packet', str(out)]) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'queued'
    with Store(root).connect() as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0


def test_seventy_item_staged_job_keeps_declared_budget_through_final_assembly(tmp_path):
    from test_materials_ner_frozen_owner_stages import typed
    from test_materials_ner_selected_catalog_stages import selected_body, no_completion
    from ingestion.materials_ner import selected_catalog_stages as selected
    bundle, inventory, declarations, relations, _, selection, decisions, links = typed()
    # Repeated fixture payloads exercise capacity and identity, not independent science.
    for n in range(6, 71):
        key = f'I{n}'
        inventory.items.append(inventory.items[0].model_copy(update={'id': key}))
        selection.decisions[key] = selection.decisions['I1'].model_copy(deep=True)
        decisions[key] = deepcopy(decisions['I1'])
    for span in inventory.span_dispositions:
        span.item_ids = [i.id for i in inventory.items if span.span_id in i.source_span_ids]
    _, _, receipt, captures, _ = inputs(bundle, inventory)
    parent = frozen.build(bundle, receipt_raw=canonical(receipt), captures=captures, required_occurrences=[])
    keys = list(decisions)
    outputs = [selected_body(declarations).model_dump(), no_completion(declarations).model_dump(),
        relations.model_dump(), selection.model_dump(),
        *[dict(schema_version='materials-source-item-group/1', work_id=bundle.work_id,
            decisions={k: decisions[k] for k in keys[n:n+4]}) for n in range(0, 70, 4)], links]
    store = Store(tmp_path/'seventy')
    job = item_worker.enqueue(store, parent, workflow=selected.WORKFLOW, max_source_items=96)
    provider = StageProvider(outputs)
    result = run_one(store, job_id=job, provider_override=provider)
    assert result['state'] == 'succeeded', result
    assert provider.calls == 23
    packet = import_packet(store, job)
    verify_packet(packet)
    assert len(packet['rows']['results']) == 70
    assert {r['local_id'] for r in packet['rows']['results']} == {f'item:I{n}' for n in range(1, 71)}
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
