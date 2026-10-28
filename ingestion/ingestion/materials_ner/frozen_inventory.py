"""Import a real standalone inventory read without pretending to run it again.

The self-contained handoff preserves original inputs, output and receipt. Exact
source-cell accounting is an engineering gate, not independent scientific Gold.
The existing staged worker owns result IDs, graph assembly and validation.
"""
from pathlib import Path
import json

from .contract import canonical, digest
from .evidence import source_catalog, selected_quotes
from .field_candidates import active_ranges
from .inventory import Inventory, validate_inventory
from .sources import Bundle, sha

FORMAT = 'materials-frozen-inventory/1'
FORMATS = {FORMAT, 'materials-frozen-inventory/2'}
ACCOUNTING = 'materials-frozen-source-occurrences/1'
CAPTURE_KEYS = ('source_bundle', 'source_catalog', 'prompt', 'frozen_schema',
                'raw_output', 'inventory', 'validation')


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('frozen_inventory_duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def literal(raw):
    return ' '.join(raw.strip().strip('$').split())


def occurrence_accounting(bundle, inventory, occurrences):
    """Bind exact coordinate occurrences to unique frozen inventory items.

    Equal numbers alone are insufficient: the item's primary selected spans
    must cover the actual source occurrence. Ambiguous joins fail admission.
    """
    if not isinstance(occurrences, list) or len(occurrences) > 512:
        raise ValueError('frozen_occurrence_budget_invalid')
    blocks = {b.id: b for b in bundle.blocks}
    catalog = source_catalog(bundle)
    seen, coordinates, items_used, rows = set(), set(), set(), []
    for occurrence in occurrences:
        if set(occurrence) != {'id', 'block_id', 'start_char', 'end_char', 'quote', 'quote_sha256'}:
            raise ValueError('frozen_occurrence_shape_invalid')
        identifier = occurrence['id']
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError('frozen_occurrence_duplicate_or_empty_id')
        seen.add(identifier)
        block = blocks.get(occurrence['block_id'])
        start, end, raw = occurrence['start_char'], occurrence['end_char'], occurrence['quote']
        if (block is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(block.text) or block.text[start:end] != raw
                or sha(raw.encode()) != occurrence['quote_sha256']):
            raise ValueError('frozen_occurrence_source_mismatch')
        key = (block.id, start, end)
        if key in coordinates:
            raise ValueError('frozen_occurrence_duplicate_coordinates')
        coordinates.add(key)
        if not any(a <= start and end <= b for a, b in active_ranges(block.text)):
            raise ValueError('frozen_occurrence_inactive_source')
        matches = []
        for item in inventory.items:
            if item.value_raw is None or literal(item.value_raw) != literal(raw):
                continue
            if any(q['block_id'] == block.id and q['start_char'] <= start and end <= q['end_char']
                   for q in selected_quotes(catalog, item.source_span_ids)):
                matches.append(item.id)
        if len(matches) != 1:
            raise ValueError('frozen_occurrence_inventory_missing_or_ambiguous')
        if matches[0] in items_used:
            raise ValueError('frozen_occurrences_share_inventory_item')
        items_used.add(matches[0])
        rows.append(dict(occurrence_id=identifier, inventory_item_id=matches[0],
            source_coordinate=dict(block_id=block.id, start_char=start, end_char=end),
            source_quote_sha256=occurrence['quote_sha256'], scientific_mapping_verified=False))
    return dict(schema=ACCOUNTING, source_cells=len(rows), rows=rows,
        inventory_items=len(inventory.items), independent_gold=False,
        full_source_coverage_established=False, scientific_acceptance=False)


def inspect(bundle, receipt_raw, captures, occurrences):
    receipt = parse(receipt_raw)
    if (receipt.get('schema') != 'materials-full-source-inventory-attempt/1'
            or receipt.get('terminal') is not True or receipt.get('provider_calls') != 1
            or receipt.get('status') != 'inventory_valid' or receipt.get('source_unchanged') is not True
            or receipt.get('scientific_acceptance') is not False
            or receipt.get('full_graph_extraction') is not False):
        raise ValueError('frozen_inventory_receipt_not_admissible')
    if set(captures) != set(CAPTURE_KEYS):
        raise ValueError('frozen_inventory_capture_keys_invalid')
    for key in CAPTURE_KEYS:
        if sha(captures[key].encode()) != receipt[key]['sha256']:
            raise ValueError('frozen_inventory_capture_hash_mismatch')
    original = Bundle.model_validate(parse(captures['source_bundle']))
    if original.work_id != bundle.work_id or receipt['work_id'] != bundle.work_id:
        raise ValueError('frozen_inventory_work_mismatch')
    # Permit only version labels and acquisition notes to differ. The old model
    # input stays in the snapshot; its metadata is never retrospectively changed.
    current = bundle.model_dump()
    parent = original.model_dump()
    if len(current['documents']) != len(parent['documents']):
        raise ValueError('frozen_inventory_source_changed')
    for doc, old in zip(current['documents'], parent['documents'], strict=True):
        for key in ('publication_version', 'version_status'):
            doc[key] = old[key]
    current['acquisition_notes'] = parent['acquisition_notes']
    if current != parent:
        raise ValueError('frozen_inventory_source_changed')
    old_catalog = source_catalog(original)
    if parse(captures['source_catalog']) != old_catalog:
        raise ValueError('frozen_inventory_source_catalog_mismatch')
    inventory = Inventory.model_validate(parse(captures['raw_output']))
    retained = Inventory.model_validate(parse(captures['inventory']))
    if inventory != retained:
        raise ValueError('frozen_inventory_output_was_rewritten')
    original_validation = validate_inventory(inventory, original)
    if (not original_validation['valid'] or original_validation != parse(captures['validation'])
            or not validate_inventory(inventory, bundle)['valid']):
        raise ValueError('frozen_inventory_not_valid')
    if receipt.get('item_count') != len(inventory.items):
        raise ValueError('frozen_inventory_receipt_count_mismatch')
    return inventory, occurrence_accounting(bundle, inventory, occurrences)


def build(bundle, *, receipt_raw, captures, required_occurrences):
    inventory, accounting = inspect(bundle, receipt_raw, captures, required_occurrences)
    body = dict(schema=FORMAT, work_id=bundle.work_id, bundle_hash=digest(bundle.model_dump()),
        bundle=bundle.model_dump(), source_receipt_raw=receipt_raw, captures=captures,
        inventory=inventory.model_dump(), required_occurrences=required_occurrences,
        source_accounting=accounting, scientific_acceptance=False, ml_training_eligible=False,
        new_model_calls=0)
    return dict(body, run_id=digest(body))


def from_files(bundle, receipt_path, occurrence_path):
    receipt_raw = Path(receipt_path).read_bytes().decode('utf-8')
    receipt = parse(receipt_raw)
    if receipt.get('schema') in {'materials-typed-source-inventory-attempt/1','materials-typed-source-inventory-attempt/2','materials-source-role-inventory-attempt/1','materials-source-role-inventory-attempt/2','materials-source-role-inventory-attempt/3','materials-source-role-inventory-attempt/4'}:
        if occurrence_path is not None and parse(Path(occurrence_path).read_text()) != []:
            raise ValueError('typed_inventory_obligations_cannot_be_overridden')
        from .typed_inventory_handoff import from_files as typed_from_files
        return typed_from_files(bundle, receipt_path)
    captures = {key: Path(receipt[key]['path']).read_bytes().decode('utf-8') for key in CAPTURE_KEYS}
    if occurrence_path is None:
        raise ValueError('legacy_frozen_inventory_requires_occurrence_file')
    occurrences = parse(Path(occurrence_path).read_bytes().decode('utf-8'))
    return build(bundle, receipt_raw=receipt_raw, captures=captures, required_occurrences=occurrences)


def verify(snapshot, bundle=None):
    if snapshot.get('schema') == 'materials-frozen-inventory/2':
        from .typed_inventory_handoff import verify as verify_typed
        return verify_typed(snapshot, bundle)
    allowed = {'schema', 'work_id', 'bundle_hash', 'bundle', 'source_receipt_raw',
        'captures', 'inventory', 'required_occurrences', 'source_accounting',
        'scientific_acceptance', 'ml_training_eligible', 'new_model_calls', 'run_id'}
    if set(snapshot) != allowed or snapshot['schema'] != FORMAT:
        raise ValueError('frozen_inventory_snapshot_shape_invalid')
    current = Bundle.model_validate(snapshot['bundle']) if bundle is None else bundle
    candidate = build(current, receipt_raw=snapshot['source_receipt_raw'],
        captures=snapshot['captures'], required_occurrences=snapshot['required_occurrences'])
    if candidate != snapshot:
        raise ValueError('frozen_inventory_snapshot_mismatch')
    return Inventory.model_validate(snapshot['inventory'])


def outcome_accounting(snapshot, report):
    """Retain every required source cell even if the worker cannot build a graph."""
    if snapshot.get('schema') == 'materials-frozen-inventory/2':
        from .typed_inventory_handoff import outcome_accounting as typed_accounting
        return typed_accounting(snapshot, report)
    from .item_stages import result_id
    results = {r['id']: r for r in report.get('extraction', {}).get('results', [])}
    occurrences = {o['id']: o for o in snapshot['required_occurrences']}
    rows = []
    for binding in snapshot['source_accounting']['rows']:
        key = result_id(binding['inventory_item_id'])
        result = results.get(key)
        raw = (result.get('quantity') or {}).get('raw') if result else None
        status = ('not_materialized' if result is None else 'source_value_changed'
            if raw is None or literal(raw) != literal(occurrences[binding['occurrence_id']]['quote'])
            else 'materialized_for_review')
        rows.append(dict(binding, expected_result_id=key, status=status))
    return dict(schema=ACCOUNTING, parent_snapshot_id=snapshot['run_id'],
        source_cells=len(rows), rows=rows,
        materialized_cells=sum(r['status'] == 'materialized_for_review' for r in rows),
        fully_materialized=all(r['status'] == 'materialized_for_review' for r in rows),
        independent_gold=False, full_source_coverage_established=False, scientific_acceptance=False)
