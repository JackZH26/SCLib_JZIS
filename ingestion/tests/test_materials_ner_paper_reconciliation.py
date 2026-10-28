"""Missing source/result obligations cannot be hidden by successful prose or imports."""
from copy import deepcopy
from pathlib import Path
import pytest
from ingestion.materials_ner import paper_coverage as pc,reviewed_proposals as rp
from test_materials_ner_reviewed_proposals import prepared,reframe,at,packet,AUTHOR,NOW,graph
from test_materials_ner_visual_regions import region_case,make_packet


def authored(m,b,*,units=None,dispositions=None,exclusions=None):
    seed=pc.seed_reconciliation(m,b,author=AUTHOR,created_at=NOW)
    return pc.reconciliation(manifest=m,bundle=b,units=units if units is not None else seed['units'],
        dispositions=dispositions if dispositions is not None else seed['dispositions'],
        exclusions=exclusions or [],author=AUTHOR,created_at=NOW)


def complete_case(prepared,*,assertions=None):
    b,m=prepared[3:]
    assertion=dict(id='onset',kind='text_result',anchor=at(b.blocks[0],'5 K'),visual=None,note='Synthetic literal onset.')
    m=reframe(m,b,assertions=assertions if assertions is not None else [assertion],supplement=dict(status='reviewed_none_reported',
        note='Synthetic source fixture is complete.',anchors=[at(b.blocks[0],b.blocks[0].text)]))
    p=packet(prepared,manifest=m,scope_review_complete=True)
    units=[dict(id=x['id'],status='reviewed',note='Synthetic original unit inspected.') for x in pc.review_units(m,b)]
    dispositions=[dict(assertion_id=x['id'],action='bound',targets=[dict(packet_hash=p['packet_hash'],result_id='r')],repeat_of=None,
        note='Synthetic source-backed result binding.') for x in m['assertions']]
    return b,m,p,units,dispositions


def test_explicit_reconciliation_is_required_even_after_structured_scope_review(prepared):
    b,m,p,u,d=complete_case(prepared)
    assert 'source_reconciliation_missing' in rp.paper_status(m,b,[p])['holds']
    ledger=authored(m,b,units=u,dispositions=d)
    status=rp.paper_status(m,b,[p],ledger)
    assert status['paper_ready_for_independent_review'] and status['source_reconciliation']['mechanically_reconciled']
    assert not status['scientific_acceptance'] and not status['ml_training_eligible']


@pytest.mark.parametrize('change',['drop_unit','duplicate_unit','unknown_unit','drop_assertion','unknown_assertion','duplicate_assertion','rehashed_identity'])
def test_missing_or_mutated_inventory_cannot_certify_completion(prepared,change):
    b,m,p,u,d=complete_case(prepared)
    if change=='drop_unit':u=[]
    elif change=='duplicate_unit':u.append(deepcopy(u[0]))
    elif change=='unknown_unit':u[0]['id']='unknown'
    elif change=='drop_assertion':d=[]
    elif change=='unknown_assertion':d[0]['assertion_id']='unknown'
    elif change=='duplicate_assertion':d.append(deepcopy(d[0]))
    if change=='rehashed_identity':
        ledger=authored(m,b,units=u,dispositions=d);ledger['work_id']='arxiv:wrong'
        from ingestion.materials_ner.contract import digest
        ledger['reconciliation_hash']=digest({k:v for k,v in ledger.items() if k!='reconciliation_hash'})
        with pytest.raises(ValueError,match='replay_mismatch'):rp.paper_status(m,b,[p],ledger)
    else:
        with pytest.raises(ValueError):authored(m,b,units=u,dispositions=d)


@pytest.mark.parametrize('change',['held','wrong_packet','wrong_result','unread_unit'])
def test_held_or_stale_links_cannot_become_closed_results(prepared,change):
    b,m,p,u,d=complete_case(prepared)
    if change=='held':d[0].update(action='held',targets=[])
    elif change=='wrong_packet':d[0]['targets'][0]['packet_hash']='0'*64
    elif change=='wrong_result':d[0]['targets'][0]['result_id']='missing'
    else:u[0]['status']='pending'
    status=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))
    assert not status['paper_ready_for_independent_review']
    assert not status['source_reconciliation']['mechanically_reconciled']


def test_equal_value_or_nearby_caption_is_not_an_original_quantity_witness(prepared):
    b=prepared[3];a=dict(id='unrelated',kind='text_result',anchor=at(b.blocks[0],'The criterion is onset.'),visual=None,
        note='Synthetic unrelated assertion; no quantity appears here.')
    b,m,p,u,d=complete_case(prepared,assertions=[a])
    s=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))['source_reconciliation']
    assert s['assertion_dispositions'][0]['issue']=='result_source_disconnected'
    assert s['unlisted_results']


def test_extra_candidate_must_have_its_own_inventory_entry(prepared):
    b,m,p,u,d=complete_case(prepared,assertions=[])
    status=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))
    assert 'candidate_results_missing_from_inventory' in status['holds']


def test_repeated_mentions_require_explicit_disposition_not_numeric_deduplication(prepared):
    b=prepared[3];a=dict(id='one',kind='text_result',anchor=at(b.blocks[0],'5 K'),visual=None,note='Synthetic occurrence.')
    b,m,p,u,d=complete_case(prepared,assertions=[a,dict(a,id='two')])
    status=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))
    assert 'repeated_result_requires_explicit_disposition' in status['holds']
    d[1].update(action='repeat',targets=[],repeat_of='one',note='Explicit duplicate inventory entry for the same synthetic source occurrence.')
    status=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))
    assert status['paper_ready_for_independent_review']
    assert status['source_reconciliation']['unique_candidate_results']==1


def test_repeat_requires_its_own_source_witness_and_cycles_remain_held(prepared):
    b=prepared[3];a=dict(id='one',kind='text_result',anchor=at(b.blocks[0],'5 K'),visual=None,note='Synthetic occurrence.')
    other=dict(a,id='two',anchor=at(b.blocks[0],'The criterion is onset.'))
    b,m,p,u,d=complete_case(prepared,assertions=[a,other]);d[1].update(action='repeat',targets=[],repeat_of='one')
    s=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))['source_reconciliation']
    assert s['assertion_dispositions'][1]['issue']=='result_source_disconnected'
    d[0].update(action='repeat',targets=[],repeat_of='two')
    s=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))['source_reconciliation']
    assert {x['issue'] for x in s['assertion_dispositions']}=={'repeat_cycle'}


def test_exclusion_cannot_discharge_an_inventoried_result(prepared):
    b,m,p,u,d=complete_case(prepared)
    excluded=dict(id='exclude',anchor=m['assertions'][0]['anchor'],reason='model_input',note='Deliberately contradictory synthetic claim.')
    s=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d,exclusions=[excluded]))
    assert 'source_assertion_also_excluded' in s['holds']
    excluded['reason']='unpublished_source'
    with pytest.raises(ValueError,match='published_source_excluded'):authored(m,b,units=u,dispositions=d,exclusions=[excluded])


def test_broader_exclusion_cannot_hide_a_known_result_inside_it(prepared):
    b,m,p,u,d=complete_case(prepared)
    excluded=dict(id='exclude',anchor=at(b.blocks[0],b.blocks[0].text),reason='model_input',note='Synthetic overbroad exclusion.')
    s=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d,exclusions=[excluded]))
    assert s['source_reconciliation']['contradictory_exclusion_ids']==['exclude']
    assert not s['paper_ready_for_independent_review']


def test_no_file_reads_or_provider_call_needed_for_reconciliation(prepared,monkeypatch):
    b,m,p,u,d=complete_case(prepared);ledger=authored(m,b,units=u,dispositions=d)
    monkeypatch.setattr(Path,'read_bytes',lambda *a,**k:(_ for _ in ()).throw(AssertionError('file read')))
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:(_ for _ in ()).throw(AssertionError('file read')))
    assert rp.paper_status(m,b,[p],ledger)['paper_ready_for_independent_review']


def test_visual_binding_discharges_only_its_label_not_the_page(region_case):
    case,original=region_case;p=make_packet(case,original);m=case['manifest'];b=case['bundle']
    ledger=pc.seed_reconciliation(m,b,author=AUTHOR,created_at=NOW)
    d=ledger['dispositions'];d[0].update(action='bound',targets=[dict(packet_hash=p['packet_hash'],result_id='r')])
    u=ledger['units']
    for unit in u:unit['status']='reviewed'
    s=rp.paper_status(m,b,[p],authored(m,b,units=u,dispositions=d))
    assert s['source_reconciliation']['source_assertions_with_binding']==1
    assert 'visual_unit_review_not_established' in s['holds'] and not s['paper_ready_for_independent_review']


def test_duplicate_current_packet_is_not_additional_coverage(prepared):
    b,m,p,u,d=complete_case(prepared)
    with pytest.raises(ValueError,match='current_packet_identity'):rp.paper_status(m,b,[p,p],authored(m,b,units=u,dispositions=d))


def test_unpublished_comment_cannot_hide_adjacent_published_text(prepared):
    from ingestion.materials_ner.sources import sha
    b,m=prepared[3:];b=b.model_copy(deep=True);block=b.blocks[0]
    block.text+='% An unpublished magnetic-method sentence.\n';block.sha256=sha(block.text.encode())
    b.documents[0].source_kind='original_tex'
    roles=deepcopy(m['roles']);roles[0]['end_char']=len(block.text);roles[0]['anchors']=[at(block,block.text)]
    m=reframe(m,b,roles=roles)
    e=dict(id='comment',anchor=at(block,'% An unpublished magnetic-method sentence.'),reason='unpublished_source',note='Synthetic comment.')
    assert authored(m,b,exclusions=[e])['exclusions']==[e]
    e['anchor']=at(block,block.text)
    with pytest.raises(ValueError,match='unpublished_source_not_proven'):authored(m,b,exclusions=[e])
