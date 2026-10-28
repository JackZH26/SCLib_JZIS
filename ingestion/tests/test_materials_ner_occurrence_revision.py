"""Revision and evaluation regressions from held/additional source alias failures."""
from copy import deepcopy
import jsonschema
import pytest

from ingestion.materials_ner import staged_revision as revision, occurrence_audit
from ingestion.materials_ner.contract import digest
from ingestion.materials_ner.sources import Block, sha
from test_materials_ner_staged_revision import fixture, execute
from test_materials_ner_item_stages import typed
from ingestion.materials_ner.item_stages import assemble


def test_explicit_dangling_evidence_removal_replays_without_scientific_change(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path,stale_evidence=True)
    before,_=revision.resolve_parent(parent);data=before.model_dump()
    index=len(data['states'][0]['evidence'][0]['fields'])-1
    path=f'/states/0/evidence/0/fields/{index}'
    request['fields']=[dict(id='stale',path=path,expected_value_sha256=digest('/conditions/99'),
        operation='remove',concern='Evidence points to an absent condition; preserve every actual condition.',source_span_ids=['S1'])]
    response.update(request_sha256=digest(request),selections={'stale':dict(action='remove',value=None,
        span_ids=['S1'],reason='There is no such condition in the frozen graph.')})
    _,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet)
    data['states'][0]['evidence'][0]['fields'].pop()
    assert after.model_dump()==data
    assert packet['receipt']['revision_audit']['changes'][0]['stale_evidence_target']['missing_fields']==['/conditions/99']
    assert not packet['scientific_acceptance']


@pytest.mark.parametrize('field',['/conditions/0','/preparation_raw','/sample_id'])
def test_existing_field_evidence_including_null_cannot_be_discarded(field):
    data={'states':[{'conditions':[{'quantity':{'value':9}}],'sample_id':'sample:1','preparation_raw':None,
                     'evidence':[{'fields':[field],'span_ids':['S1']}]}]}
    with pytest.raises(ValueError,match='still_addresses_field'):
        revision.stale_evidence_target(data,'/states/0/evidence/0')


def test_stale_reference_removal_rejects_mixed_live_pointer_and_empty_leaf():
    data={'states':[{'conditions':[],'sample_id':'s','evidence':[{'fields':['/sample_id','/conditions/0'],'span_ids':['S1']}]}]}
    with pytest.raises(ValueError,match='still_addresses_field'):
        revision.stale_evidence_target(data,'/states/0/evidence/0')
    data['states'][0]['evidence'][0]['fields']=['/conditions/0']
    with pytest.raises(ValueError,match='empty_reference'):
        revision.stale_evidence_target(data,'/states/0/evidence/0/fields/0')
    assert revision.stale_evidence_target(data,'/states/0/evidence/0')['missing_fields']==['/conditions/0']


def test_context_disposition_transition_is_explicit_and_cannot_retarget_identity(tmp_path):
    store,bundle,parent,request,response=fixture(tmp_path)
    before,_=revision.resolve_parent(parent);old=before.model_dump()['context_dispositions'][0]
    value=dict(context_id=old['context_id'],resolution='unresolved',bindings=[],
               explanation='Synthetic source applicability needs a separate scientific read.')
    request['fields']=[dict(id='context',path='/context_dispositions/0',expected_value_sha256=digest(old),
        operation='replace',concern='Reread the original context applicability.',source_span_ids=['S1'])]
    response.update(request_sha256=digest(request),selections={'context':dict(action='replace',value=value,
        span_ids=['S1'],reason='Retain this known context as explicitly unresolved.')})
    _,packet=execute(store,bundle,parent,request,response)
    after,_=revision.resolve_parent(packet);expected=before.model_dump();expected['context_dispositions'][0]=value
    assert after.model_dump()==expected
    invalid=deepcopy(response);invalid['selections']['context']['value']['context_id']='another-context'
    with pytest.raises(ValueError,match='context_identity_changed'):
        revision.apply_edits(parent,bundle,revision.NativeEdits.model_validate(invalid),review_request=request)


def audit_fixture():
    bundle,inventory,_,catalog,decisions,links=typed()
    graph,coverage,_=assemble(bundle,inventory,catalog,decisions,links)
    return bundle,inventory.model_dump(),graph.expand(bundle).model_dump(),coverage['result_mapping']


def test_held_original_is_not_recovered_by_same_source_value_under_additional_alias():
    bundle,inventory,extraction,mapping=audit_fixture();item=inventory['items'][0]
    # Make a controlled original-source occurrence with an exact lexical value.
    item['value_raw']='7 K';rid=next(rid for rid,ids in mapping.items() if item['id'] in ids)
    addition=dict(item,id='additional:1');mapping[rid]=['additional:1']
    next(r for r in extraction['results'] if r['id']==rid)['quantity']['raw']='7 K'
    hold=dict(item_id=item['id'],reason='insufficient_context',explanation='Synthetic owner hold.')
    before=digest([inventory,extraction,mapping])
    report=occurrence_audit.audit(inventory,bundle,mapping,[hold],[addition],extraction)
    row=report['rows'][0]
    assert row['status']=='held' and row['result_ids']==[]
    assert row['source_value_literal_present_result_ids']==[rid]
    assert report['original_items_emitted_once']==len(inventory['items'])-1
    assert not report['original_item_closure']
    finding=next(f for f in report['findings'] if f['code']=='held_original_overlaps_emitted_addition')
    assert not finding['counts_as_original_item_recovery'] and not finding['automatic_merge_permitted']
    assert digest([inventory,extraction,mapping])==before


def test_equal_literal_elsewhere_is_not_occurrence_identity_and_inequality_is_distinct():
    bundle,inventory,extraction,mapping=audit_fixture();item=inventory['items'][0];item['value_raw']='6 T'
    rid=next(rid for rid,ids in mapping.items() if item['id'] in ids);mapping[rid]=['additional:1']
    # Duplicate text at another document coordinate cannot close the original.
    block=bundle.blocks[0];text=block.text
    bundle=bundle.model_copy(deep=True)
    bundle.blocks.append(Block(id=block.id+':other',document_id=block.document_id,ordinal=99,
        locator='synthetic:different-original-location',text=text,sha256=sha(text.encode())))
    source=occurrence_audit.source_catalog(bundle)
    span=next(k for k,v in source['spans'].items() if v['block_id']==block.id+':other')
    addition=dict(item,id='additional:1',source_span_ids=[span])
    hold=dict(item_id=item['id'],reason='unresolved',explanation='Unresolved original occurrence.')
    report=occurrence_audit.audit(inventory,bundle,mapping,[hold],[addition],extraction)
    assert not any('overlaps' in f['code'] for f in report['findings'])
    addition['source_span_ids']=item['source_span_ids'];addition['value_raw']='>=6 T'
    report=occurrence_audit.audit(inventory,bundle,mapping,[hold],[addition],extraction)
    assert not any('overlaps' in f['code'] for f in report['findings'])


def test_failed_graph_preserves_every_missing_original_in_denominator():
    bundle,inventory,_,_=audit_fixture()
    report=occurrence_audit.audit(inventory,bundle,{},[],[],None)
    assert report['original_items_missing']==len(inventory['items'])
    assert not report['original_item_closure'] and not report['independent_recall_denominator_available']
