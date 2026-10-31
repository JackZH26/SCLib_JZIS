"""Projector amendments keep original scope, findings and dependency obligations."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from ingestion.materials_ner import review_amendments as amendments, projector_proposals as adapter
from ingestion.materials_ner import source_projector as projector, reviewed_reader as reader
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.proposals import review_rows
from ingestion.materials_ner.contract import parse_extraction
from test_materials_ner_projector_proposals import terminal, findings
from test_materials_ner_source_projector import queued, Fake
from test_materials_ner_reviewed_proposals import prepared, graph, at, AUTHOR, NOW


def arguments(parent, *, result_ids=None):
    anchor = at(type('Block', (), parent['bundle']['blocks'][0]), 'The criterion is onset.')
    reviews = [dict(result_id=r['id'], fields={field:dict(disposition='not_reviewed', note='Synthetic review obligation.', anchors=[])
        for field in amendments.FIELDS}, holds=['independent_scientific_review_pending'])
        for r in parent['receipt']['extraction']['results'] if result_ids is None or r['id'] in result_ids]
    return dict(bundle=parent['bundle'], changes=[dict(path='/states/0/label', before=parent['receipt']['extraction']['states'][0]['label'],
        after='Synthetic reviewed state label', reason='Synthetic explicit editorial change.', anchors=[anchor])],
        reviews=reviews, author=AUTHOR, created_at=NOW)


def test_pending_source_findings_survive_unrelated_amendment(queued, tmp_path):
    store, _, job, bundle, _ = queued; raw=graph(bundle)
    derived=deepcopy(raw['results'][0]);derived['id']='derived';derived['dependencies']=[dict(result_id='r',relation='derived_from')]
    raw['results'].append(derived)
    projector.run(store,job,provider_override=Fake(raw))
    f=findings(tmp_path/'findings.json',store,job,bundle)
    parent=adapter.build(store.root,job,review_findings=f);before=deepcopy(parent)
    value=amendments.build(parent,**arguments(parent,result_ids=['r']))
    assert amendments.verify(value,parent)==value and parent==before
    assert value['affected_result_ids']==['derived','r'] and value['unreviewed_result_ids']==['derived']
    assert len(value['source_review']['findings'])==2
    assert not value['source_review']['paper_completed'] and not value['source_review']['independent_review']
    rows=review_rows(parse_extraction(value['graph']),value['validation'])
    assert all(r['review_status']=='quarantined' for r in rows['results'])
    assert all('state_has_validation_issues' in r['issues'] for r in rows['results'])
    assert not any(i['path']=='/paper' for i in value['validation']['issues'])


def test_amendment_does_not_promote_context_values_into_target(queued,tmp_path):
    store,input_path,_,bundle,_=queued;request=json.loads(input_path.read_text())
    scope=json.loads(Path(request['scope']['path']).read_text());b=bundle.blocks[0];cut=b.text.index('The criterion')
    scope['passages']=[dict(block_id=b.id,start_char=0,end_char=cut,role='context'),
                       dict(block_id=b.id,start_char=cut,end_char=len(b.text),role='target')]
    scope_path=tmp_path/'restricted_scope.json';scope_path.write_text(canonical(scope))
    request['scope']=reader.reference(scope_path);new=tmp_path/'restricted_input.json';new.write_text(canonical(request))
    job=projector.enqueue(store,new);projector.run(store,job,provider_override=Fake(graph(bundle)))
    parent=adapter.build(store.root,job)
    value=amendments.build(parent,**arguments(parent))
    assert 'result_without_target_original_evidence' in {i['code'] for i in value['validation']['issues']}
    assert not value['validation']['valid']


def test_structurally_invalid_parent_cannot_allocate_repair_entities(queued):
    store,_,job,bundle,_=queued;raw=graph(bundle);raw['results'][0]['protocol_id']='missing'
    projector.run(store,job,provider_override=Fake(raw));parent=adapter.build(store.root,job)
    with pytest.raises(ValueError,match='amendment_parent_graph_unavailable'):
        amendments.build(parent,bundle=parent['bundle'],changes=[],reviews=[],author=AUTHOR,created_at=NOW)


def test_parent_finding_cannot_be_removed_from_rehashed_amendment(terminal,tmp_path):
    store,job,bundle,_=terminal
    parent=adapter.build(store.root,job,review_findings=findings(tmp_path/'f.json',store,job,bundle))
    value=amendments.build(parent,**arguments(parent));value['source_review']['findings']=[]
    from ingestion.materials_ner.contract import digest
    value['amendment_id']=digest({k:v for k,v in value.items() if k!='amendment_id'})
    with pytest.raises(ValueError,match='amendment_replay_mismatch'):amendments.verify(value,parent)
