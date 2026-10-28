"""Authored transport/physics fixtures, never independent scientific data."""
from copy import deepcopy

import jsonschema
import pytest

from ingestion.materials_ner import typed_inventory as typed, typed_inventory_handoff as handoff
from ingestion.materials_ner import frozen_inventory, item_worker, pdf_layout
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.sources import Bundle,sha
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_item_stages import fixture, StageProvider, responses


def inputs():
    b,old,_,catalog,decisions,links=fixture();cat=source_catalog(b)
    entries=[]
    for item in old.items:
        r=decisions[item.id]['observation']['result']
        common=dict(sample_description=item.sample_raw,quantity_description=item.quantity_name_raw,
            quantity_kind=r['quantity_kind'],source_span_ids=item.source_span_ids,context_span_ids=item.context_span_ids,
            attribution=dict(origin=r['origin'],source_role=r['source_role'],span_ids=item.source_span_ids))
        if r['quantity_kind']=='non_detection':
            entries.append(dict(common,type='unvalued_result',statement_raw=item.value_raw,
                value_status='explicit_non_detection',unresolved_reason='No resolvable supercurrent in the reported current window.'))
        else:entries.append(dict(common,type='numeric_result',value_raw=item.value_raw,unit=r['quantity']['unit'],
            unit_span_ids=item.source_span_ids,unresolved_reason=None))
    model=typed.TypedInventory(schema_version=typed.VERSION,work_id=b.work_id,entries=entries,
        context_assertions=[c.model_dump(exclude={'id'}) for c in old.context_assertions],
        span_assessments={key:dict(read=True,non_result_role='context_only',reason='Original source read for this authored fixture.')
            for key in typed.targets(cat)},unread_block_ids=[],limitations=[])
    return b,model,catalog,decisions,links


def snapshot():
    b,model,catalog,decisions,links=inputs();inventory,proof=typed.project(model,b)
    captures=dict(source_bundle=canonical(b.model_dump()),source_catalog=canonical(source_catalog(b)),
        prompt=typed.render(b),frozen_schema=canonical(typed.output_schema(b)),raw_output=canonical(model.model_dump()),
        typed_inventory=canonical(model.model_dump()),inventory=canonical(inventory.model_dump()),
        validation=canonical(proof['validation']),projection=canonical(proof),layout='null')
    receipt=dict(schema='materials-typed-source-inventory-attempt/1',work_id=b.work_id,terminal=True,provider_calls=1,
        status='typed_inventory_valid',source_unchanged=True,scientific_acceptance=False,full_graph_extraction=False,
        item_count=len(inventory.items),model='authored-test-only',
        **{key:dict(path=f'/authored-test/{key}',sha256=sha(raw.encode())) for key,raw in captures.items()})
    parent=handoff.build(b,receipt_raw=canonical(receipt),captures=captures)
    return b,model,parent,receipt,captures,catalog,decisions,links


def test_generated_ids_close_dispositions_and_preserve_equal_value_multiplicity():
    b,model,*_=inputs();jsonschema.validate(model.model_dump(),typed.output_schema(b))
    inventory,proof=typed.project(model,b)
    assert [i.id for i in inventory.items]==['I1','I2','I3','I4','I5']
    assert inventory.items[-1].value_raw is None
    assert proof['projected_validation']['valid']
    shared=[o for o in proof['occurrences'] if len(o['item_ids'])==2]
    assert any(o['item_ids']==['I3','I4'] for o in shared)
    assert not proof['independent_observation_identity_verified']


@pytest.mark.parametrize('mutation,code',[
    ('pressure_unit','typed_inventory_kind_unit_mismatch'),
    ('false_inline_unit','typed_inventory_inline_unit_mismatch'),
    ('origin_without_evidence','typed_inventory_attribution_evidence_missing'),
    ('unknown_kind','typed_inventory_kind_unknown'),
    ('unknown_without_reason','typed_inventory_unmapped_reason_missing'),
    ('missing_span_read','typed_inventory_span_read_coverage'),
    ('unread','typed_inventory_unread_source'),
    ('repeated_span','typed_inventory_source_reference_invalid'),
    ('false_non_detection','typed_inventory_non_detection_status_mismatch'),
])
def test_invalid_first_read_cannot_be_frozen(mutation,code):
    b,m,*_=inputs()
    if mutation=='pressure_unit':m.entries[0].unit='GPa'
    elif mutation=='false_inline_unit':m.entries[0].value_raw='0.8 GPa'
    elif mutation=='origin_without_evidence':m.entries[0].attribution.span_ids=[]
    elif mutation=='unknown_kind':m.entries[0].quantity_kind='fictional'
    elif mutation=='unknown_without_reason':m.entries[0].quantity_kind='unmapped'
    elif mutation=='missing_span_read':m.span_assessments.pop(next(iter(m.span_assessments)))
    elif mutation=='unread':next(iter(m.span_assessments.values())).read=False
    elif mutation=='repeated_span':m.entries[0].source_span_ids*=2
    else:m.entries[-1].value_status='figure_not_digitized'
    assert code in {i['code'] for i in typed.inspect(m,b)['issues']}
    with pytest.raises(ValueError,match='typed_inventory_not_valid'):typed.project(m,b)


def test_figure_value_and_qualitative_outcome_do_not_become_false_non_detection():
    b,m,*_=inputs();e=m.entries[-1];e.quantity_kind='tc';e.value_status='figure_not_digitized'
    inventory,proof=typed.project(m,b)
    assert inventory.items[-1].value_raw is None
    assert proof['typed_entries'][-1]['value_status']=='figure_not_digitized'
    assert proof['typed_entries'][-1]['quantity_kind']=='tc'


@pytest.mark.parametrize('key',handoff.CAPTURE_KEYS)
def test_raw_capture_changes_fail_admission(key):
    b,_,_,receipt,captures,*_=snapshot();captures[key]+=' '
    with pytest.raises(ValueError,match='capture_hash_mismatch'):
        handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


def test_raw_response_rewrite_and_rehashed_projection_tamper_are_rejected():
    b,_,parent,receipt,captures,*_=snapshot()
    altered=deepcopy(parent);altered['inventory']['items'][0]['sample_raw']='rewritten'
    altered['run_id']=digest({k:v for k,v in altered.items() if k!='run_id'})
    with pytest.raises(ValueError,match='snapshot_mismatch'):frozen_inventory.verify(altered)
    captures['typed_inventory']=captures['typed_inventory'].replace('Sample A','rewritten')
    receipt['typed_inventory']['sha256']=sha(captures['typed_inventory'].encode())
    with pytest.raises(ValueError,match='output_rewritten'):
        handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


def test_real_worker_path_uses_typed_parent_and_preserves_failure_holds(tmp_path):
    b,_,parent,_,_,catalog,decisions,links=snapshot()
    assert frozen_inventory.verify(parent)==item_worker.verify_parent(parent,b)
    store=Store(tmp_path/'worker');job=item_worker.enqueue(store,parent,group_size=2)
    provider=StageProvider(responses(b,catalog,decisions,links))
    result=run_one(store,job_id=job,provider_override=provider)
    assert result['state']=='succeeded',result
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['config']['frozen_inventory_snapshot_version']==handoff.FORMAT
    assert packet['receipt']['frozen_source_accounting']['materialized_items']==5
    assert packet['receipt']['frozen_source_accounting']['source_cells']==0
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
    changed=deepcopy(packet['receipt']);changed['config']['frozen_inventory_snapshot_version']=frozen_inventory.FORMAT
    with pytest.raises(ValueError,match='config_mismatch'):item_worker.verify_receipt(changed,b,packet['raw_output'])


def test_planned_id_wrong_type_or_changed_value_does_not_close_obligation():
    _,_,parent,*_=snapshot()
    assert not handoff.outcome_accounting(parent,{})['fully_materialized']
    def status(kind,raw):
        report=dict(extraction=dict(results=[dict(id='item:I1',quantity_kind=kind,quantity=dict(raw=raw,status='reported'))]))
        return handoff.outcome_accounting(parent,report)['rows'][0]['status']
    assert status('tc','999 K')=='source_value_changed_requires_review'
    assert status('critical_pressure','39 K')=='typed_result_kind_changed_requires_review'


def test_cli_freezes_typed_capture_without_fake_table_occurrences(tmp_path,capsys):
    from ingestion.materials_ner.cli import main
    b,_,_,receipt,captures,*_=snapshot()
    for key,raw in captures.items():
        p=tmp_path/(key+'.json');p.write_text(raw);receipt[key]['path']=str(p)
    rp=tmp_path/'receipt.json';rp.write_text(canonical(receipt));out=tmp_path/'frozen.json'
    assert main(['--root',str(tmp_path/'queue'),'freeze-inventory','--bundle',receipt['source_bundle']['path'],
        '--source-receipt',str(rp),'--out',str(out)])==0
    frozen_inventory.verify(__import__('json').loads(out.read_text()))
    assert __import__('json').loads(capsys.readouterr().out)['source_cells']==0


def layout_fixture():
    b,*_=inputs();raw=b.model_dump();raw['documents'][0].update(source_kind='original_pdf',source_sha256='a'*64)
    raw['blocks'][0]['locator']='pdf_page:1';b=Bundle.model_validate(raw)
    xml='<html><body><doc><page width="600" height="800"><flow><block xMin="40" yMin="60" xMax="280" yMax="80"><line xMin="40" yMin="60" xMax="280" yMax="80"><word xMin="40" yMin="60" xMax="70" yMax="80">Run</word><word xMin="75" yMin="60" xMax="100" yMax="80">#3</word></line></block></flow></page></doc></body></html>'
    return b,xml


def test_layout_keeps_boxes_and_does_not_reorder_original_text():
    b,xml=layout_fixture();before=b.model_dump()
    layout=pdf_layout.build(b,pdf_sha256='a'*64,bbox_xml=xml,producer='authored fixture')
    assert pdf_layout.verify(layout,b)==layout and b.model_dump()==before
    assert layout['pages'][0]['blocks'][0]['text']=='Run #3'
    assert not layout['semantic_reading_order_verified']
    assert 'parser heuristics' in pdf_layout.render(layout,b)
    assert 'rounded to 0.1 point' in pdf_layout.render(layout,b)
    layout['pages'][0]['blocks'][0]['text']='Run #1'
    with pytest.raises(ValueError,match='reconstruction_mismatch'):pdf_layout.verify(layout,b)


def test_layout_wrong_pdf_and_external_entities_are_rejected():
    b,xml=layout_fixture()
    with pytest.raises(ValueError,match='source_not_admitted'):
        pdf_layout.build(b,pdf_sha256='b'*64,bbox_xml=xml,producer='authored fixture')
    with pytest.raises(ValueError,match='xml_bound_or_entity'):
        pdf_layout.build(b,pdf_sha256='a'*64,bbox_xml='<!ENTITY x "a">'+xml,producer='authored fixture')


def test_invalid_pdf_font_controls_are_visible_and_original_bytes_survive():
    b,xml=layout_fixture();xml=xml.replace('Run','R\x02un')
    layout=pdf_layout.build(b,pdf_sha256='a'*64,bbox_xml=xml,producer='authored fixture')
    assert layout['bbox_xml']==xml and layout['bbox_xml_sha256']==sha(xml.encode())
    assert layout['xml_parse_replacements']==[dict(xml_character_offset=xml.index('\x02'),codepoint=2,
        auxiliary_marker='[UNRESOLVED-PDF-GLYPH-U+0002]')]
    assert 'UNRESOLVED-PDF-GLYPH' in layout['pages'][0]['blocks'][0]['text']
    assert pdf_layout.verify(layout,b)==layout
