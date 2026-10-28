"""Replayable typed first-read handoff; preserve raw model output and projection."""
from pathlib import Path

from .contract import digest
from .evidence import source_catalog
from .sources import Bundle,sha
from . import typed_inventory as typed, pdf_layout

FORMAT='materials-frozen-inventory/2'
CAPTURE_KEYS=('source_bundle','source_catalog','prompt','frozen_schema','raw_output',
    'typed_inventory','inventory','validation','projection','layout')


def require_admissible_receipt(receipt):
    if (receipt.get('schema') not in {'materials-typed-source-inventory-attempt/1','materials-typed-source-inventory-attempt/2'}
            or receipt.get('status')!='typed_inventory_valid' or receipt.get('terminal') is not True
            or receipt.get('provider_calls')!=1 or receipt.get('source_unchanged') is not True
            or receipt.get('scientific_acceptance') is not False or receipt.get('full_graph_extraction') is not False):
        raise ValueError('typed_frozen_receipt_not_admissible')


def build(bundle,*,receipt_raw,captures,required_occurrences=None):
    from .frozen_inventory import parse
    receipt=parse(receipt_raw)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/4':
        from .source_piece_inventory import build_handoff
        return build_handoff(bundle,receipt_raw=receipt_raw,captures=captures,required_occurrences=required_occurrences)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/3':
        from .source_keyed_inventory import build_handoff
        return build_handoff(bundle,receipt_raw=receipt_raw,captures=captures,required_occurrences=required_occurrences)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/2':
        from .source_role_inventory import build_selection_handoff
        return build_selection_handoff(bundle,receipt_raw=receipt_raw,captures=captures,required_occurrences=required_occurrences)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/1':
        from .source_role_inventory import build_handoff
        return build_handoff(bundle,receipt_raw=receipt_raw,captures=captures,required_occurrences=required_occurrences)
    require_admissible_receipt(receipt)
    selected = typed
    if receipt['schema'] == 'materials-typed-source-inventory-attempt/2':
        from . import typed_inventory_v2 as selected
    if set(captures)!=set(CAPTURE_KEYS):raise ValueError('typed_frozen_capture_keys_invalid')
    for key in CAPTURE_KEYS:
        if sha(captures[key].encode())!=receipt[key]['sha256']:raise ValueError('typed_frozen_capture_hash_mismatch')
    original=Bundle.model_validate(parse(captures['source_bundle']))
    if original!=bundle or receipt['work_id']!=bundle.work_id:raise ValueError('typed_frozen_source_changed')
    if parse(captures['source_catalog'])!=source_catalog(bundle):raise ValueError('typed_frozen_catalog_mismatch')
    layout=parse(captures['layout'])
    if layout is not None:pdf_layout.verify(layout,bundle)
    if (parse(captures['frozen_schema'])!=selected.output_schema(bundle)
            or captures['prompt']!=selected.render(bundle,layout)):
        raise ValueError('typed_frozen_input_contract_mismatch')
    model=selected.TypedInventory.model_validate(parse(captures['raw_output']))
    if model.model_dump()!=parse(captures['typed_inventory']):raise ValueError('typed_frozen_output_rewritten')
    inventory,proof=selected.project(model,bundle)
    if (inventory.model_dump()!=parse(captures['inventory']) or proof!=parse(captures['projection'])
            or proof['validation']!=parse(captures['validation'])):
        raise ValueError('typed_frozen_projection_mismatch')
    if receipt.get('item_count')!=len(inventory.items):raise ValueError('typed_frozen_count_mismatch')
    obligations=[dict(inventory_item_id=i.id,value_raw=i.value_raw,source_span_ids=i.source_span_ids,
        quantity_kind=e.quantity_kind) for i,e in zip(inventory.items,model.entries,strict=True)]
    if required_occurrences is not None and obligations!=required_occurrences:
        raise ValueError('typed_frozen_obligations_mismatch')
    body=dict(schema=FORMAT,work_id=bundle.work_id,bundle_hash=digest(bundle.model_dump()),bundle=bundle.model_dump(),
        source_receipt_raw=receipt_raw,captures=captures,inventory=inventory.model_dump(),
        typed_inventory_projection=proof,required_occurrences=obligations,
        source_accounting=dict(schema='materials-frozen-result-obligations/1',source_cells=0,inventory_items=len(inventory.items),
            occurrences=proof['occurrences'],many_items_per_occurrence_allowed=True,independent_gold=False,
            full_source_coverage_established=False,scientific_acceptance=False),
        new_model_calls=0,scientific_acceptance=False,ml_training_eligible=False)
    return dict(body,run_id=digest(body))


def verify(snapshot,bundle=None):
    current=Bundle.model_validate(snapshot['bundle']) if bundle is None else bundle
    reconstructed=build(current,receipt_raw=snapshot['source_receipt_raw'],captures=snapshot['captures'],
        required_occurrences=snapshot['required_occurrences'])
    if reconstructed!=snapshot:raise ValueError('typed_frozen_snapshot_mismatch')
    from .inventory import Inventory
    return Inventory.model_validate(snapshot['inventory'])


def from_files(bundle,receipt_path):
    from .frozen_inventory import parse
    raw=Path(receipt_path).read_text();receipt=parse(raw)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/4':
        from .source_piece_inventory import require_receipt,CAPTURE_KEYS as piece_keys
        require_receipt(receipt)
        captures={key:Path(receipt[key]['path']).read_text() for key in piece_keys}
        return build(bundle,receipt_raw=raw,captures=captures)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/3':
        from .source_keyed_inventory import require_receipt,CAPTURE_KEYS as keyed_keys
        require_receipt(receipt)
        captures={key:Path(receipt[key]['path']).read_text() for key in keyed_keys}
        return build(bundle,receipt_raw=raw,captures=captures)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/2':
        from .source_role_inventory import require_selection_receipt,SELECTION_CAPTURE_KEYS
        require_selection_receipt(receipt)
        captures={key:Path(receipt[key]['path']).read_text() for key in SELECTION_CAPTURE_KEYS}
        return build(bundle,receipt_raw=raw,captures=captures)
    if receipt.get('schema')=='materials-source-role-inventory-attempt/1':
        from .source_role_inventory import require_receipt,CAPTURE_KEYS as role_keys
        require_receipt(receipt)
        captures={key:Path(receipt[key]['path']).read_text() for key in role_keys}
        return build(bundle,receipt_raw=raw,captures=captures)
    require_admissible_receipt(receipt)
    captures={key:Path(receipt[key]['path']).read_text() for key in CAPTURE_KEYS}
    return build(bundle,receipt_raw=raw,captures=captures)


def source_piece_prompt(snapshot):
    """Optional evidence ledger for the new contract; legacy prompts stay fixed."""
    if snapshot.get('schema')!=FORMAT:return ''
    from .frozen_inventory import parse
    if parse(snapshot['source_receipt_raw']).get('schema')!='materials-source-role-inventory-attempt/4':return ''
    from .source_piece_inventory import native_prompt
    return native_prompt(snapshot)


def outcome_accounting(snapshot,report):
    from .item_stages import result_id
    results={r['id']:r for r in report.get('extraction',{}).get('results',[])};rows=[]
    for obligation in snapshot['required_occurrences']:
        key=result_id(obligation['inventory_item_id']);result=results.get(key)
        if result is None:status='not_materialized'
        elif obligation['quantity_kind']!='unmapped' and result['quantity_kind']!=obligation['quantity_kind']:
            status='typed_result_kind_changed_requires_review'
        elif obligation['value_raw'] is not None and ' '.join((result.get('quantity',{}).get('raw') or '').split())!=' '.join(obligation['value_raw'].split()):
            status='source_value_changed_requires_review'
        elif obligation['value_raw'] is None and result.get('quantity',{}).get('status')=='reported':
            status='unvalued_source_became_numeric_requires_review'
        else:status='materialized_for_review'
        rows.append(dict(obligation,expected_result_id=key,status=status))
    result=dict(schema='materials-frozen-result-obligations/1',parent_snapshot_id=snapshot['run_id'],
        source_cells=0,inventory_items=len(rows),rows=rows,
        materialized_items=sum(r['status']=='materialized_for_review' for r in rows),
        fully_materialized=all(r['status']=='materialized_for_review' for r in rows),
        full_source_coverage_established=False,independent_gold=False,scientific_acceptance=False)
    if 'source_role_accounting' in snapshot:
        held=snapshot['source_role_accounting']['held_outcomes']
        result.update(held_source_outcomes=held,fully_materialized=result['fully_materialized'] and not held)
    return result
