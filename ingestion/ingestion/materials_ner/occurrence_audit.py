"""Read-only original-item accounting; lexical overlap is never result identity.

An emitted additional alias cannot rescue a held original item. These are
fallible model inventory occurrences, not independent scientific measurements
or a Gold recall denominator. Existing packets and scientific fields stay fixed.
"""
from collections import Counter

from .contract import digest
from .evidence import source_catalog, selected_quotes, equivalent_location_spans
from .sources import Bundle

POLICY = 'original_occurrence_accounting_v1'


def audit(inventory, bundle, mapping, holds, additions, extraction):
    original=inventory['items']; items=original+additions
    identifiers=[i['id'] for i in items]
    if len(identifiers)!=len(set(identifiers)):
        raise ValueError('occurrence_audit_duplicate_item')
    catalog=source_catalog(bundle)
    quotes={i['id']:selected_quotes(catalog,i['source_span_ids']) for i in items}
    by_item={i:[] for i in identifiers}
    for result_id,item_ids in mapping.items():
        if not item_ids or len(item_ids)!=len(set(item_ids)):
            raise ValueError('occurrence_audit_invalid_mapping')
        for item_id in item_ids:
            if item_id not in by_item:raise ValueError('occurrence_audit_unknown_item')
            by_item[item_id].append(result_id)
    hold_by_id={h['item_id']:h for h in holds}
    if len(hold_by_id)!=len(holds) or not set(hold_by_id)<=set(identifiers):
        raise ValueError('occurrence_audit_invalid_hold')
    results={r['id']:r for r in (extraction or {}).get('results',[])}
    if set(mapping)!=set(results):raise ValueError('occurrence_audit_result_mapping_mismatch')
    literal=lambda value:' '.join(value.split()) if isinstance(value,str) and value.strip() else None
    rows=[]; findings=[]
    for item in items:
        iid=item['id']; emitted=by_item[iid]; held=iid in hold_by_id
        status=('conflicting_emitted_and_held' if emitted and held else
                'emitted_multiple' if len(emitted)>1 else 'emitted' if emitted else 'held' if held else 'missing')
        if status in {'conflicting_emitted_and_held','emitted_multiple','missing'}:
            findings.append(dict(code='original_item_'+status if item in original else 'additional_item_'+status,item_id=iid))
        raw=literal(item.get('value_raw'))
        # Literal display presence only: no conversion, threshold equivalence,
        # formula inference or unscoped numeric comparison becomes recovery.
        literal_results=[rid for rid,r in results.items()
                         if raw is not None and literal(r['quantity'].get('raw'))==raw]
        rows.append(dict(item_id=iid,scope='original' if item in original else 'additional',
            status=status,result_ids=emitted,hold=hold_by_id.get(iid),source_quotes=quotes[iid],
            inventory_assertion=item,source_value_literal_present_result_ids=literal_results,
            source_scoped_emission=status=='emitted',scientific_identity_verified=False))
    for original_item in original:
        raw=literal(original_item.get('value_raw'))
        if raw is None:continue
        left=equivalent_location_spans(catalog,original_item['source_span_ids'])
        for addition in additions:
            if not by_item[addition['id']] or literal(addition.get('value_raw'))!=raw:continue
            overlap=left & equivalent_location_spans(catalog,addition['source_span_ids'])
            if not overlap:continue
            findings.append(dict(code=('held_original_overlaps_emitted_addition' if original_item['id'] in hold_by_id
                                       else 'original_overlaps_emitted_addition'),
                original_item_id=original_item['id'],additional_item_id=addition['id'],
                overlapping_source_span_ids=sorted(overlap),value_literal=raw,
                result_ids=by_item[addition['id']],same_scientific_result_established=False,
                automatic_merge_permitted=False,counts_as_original_item_recovery=False))
    counts=dict(Counter(r['status'] for r in rows if r['scope']=='original'))
    return dict(policy=POLICY,bundle_sha256=digest(bundle.model_dump()),inventory_sha256=digest(inventory),
        original_item_count=len(original),additional_item_count=len(additions),original_status_counts=counts,
        original_items_emitted_once=counts.get('emitted',0),original_items_held=counts.get('held',0),
        original_items_missing=counts.get('missing',0),rows=rows,findings=findings,
        original_item_closure=all(r['status']=='emitted' for r in rows if r['scope']=='original'),
        scientific_graph_unchanged=True,independent_recall_denominator_available=False,
        independent_gold=False,scientific_acceptance=False,ml_training_eligible=False,
        limitation='Model-inventory occurrence accounting only. Shared source spans and literal values flag possible alias overlap; sample, direction, criterion and observation identity require source review. Missing or held items remain in the denominator.')


def audit_packet(packet):
    from .proposals import verify_packet
    verify_packet(packet)
    before=digest(packet); root=packet; ancestry=[]
    while root['receipt']['config']['output_format']=='materials-staged-field-revision/1':
        ancestry.append(root['run_id']);root=root['receipt']['revision_parent']
    receipt=packet['receipt']; original=root['receipt']
    if original['config']['output_format'] not in {f'materials-source-item-transcript/{n}' for n in range(1,6)}:
        raise ValueError('occurrence_audit_requires_staged_root')
    coverage=receipt.get('inventory_coverage',{})
    report=audit(original['inventory'],Bundle.model_validate(root['bundle']),
        coverage.get('result_mapping',{}),coverage.get('unextracted_items',[]),
        original.get('staged_assembly',{}).get('additional_source_items',[]),receipt.get('extraction'))
    report.update(packet_sha256=before,run_id=packet['run_id'],root_run_id=root['run_id'],
                  revision_ancestry=ancestry,original_source_scope=True)
    assert before==digest(packet)
    return report
