from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ingestion.materials_ner import core_tc_audit as audit, reviewed_reader as rr
from ingestion.materials_ner.contract import canonical
from ingestion.materials_ner.providers import ProviderResult
from ingestion.materials_ner.store import Store


@pytest.fixture
def prepared(tmp_path):
    root=os.environ.get('MATERIALS_P90_CORE_BATCH')
    if not root:pytest.skip('Requires actual frozen Production-90 source data')
    path=Path(root).resolve().parent/'batch-012/FROZEN_SAMPLE.json'
    selection=json.loads(path.read_bytes())
    row=next(r for r in selection['records'] if r['work_id']=='arxiv:1205.4869')
    request=tmp_path/'REQUEST.json'
    rr.put(request,dict(schema=audit.INPUT_SCHEMA,selection=rr.reference(path),run_id=row['run_id']))
    return request,audit.prepare(request)


def output(p):
    decisions={}
    for row in p['selected']:
        record=next(r for r in p['projection']['records'] if r['result_id']==row['result_id'])
        witness=next(e for e in record['graph']['results'][0]['evidence'] if e['field']=='/quantity')
        ids=[key for key,e in p['catalog']['spans'].items() if e['block_id']==witness['block_id']
            and max(e['start_char'],witness['start_char'])<min(e['end_char'],witness['end_char'])]
        decisions[row['result_id']]=dict(verdict='indeterminate',
            rationale='Test-only provider output; no scientific verdict was performed.',evidence_ids=ids)
    return dict(decisions=decisions)


def test_source_quotes_are_resolved_from_original_catalogue_and_verdicts_not_supplied(prepared,tmp_path):
    _,p=prepared;assert 'reviewer_identity' not in p['prompt']
    assert 'source_audit_receipt' not in p['prompt']
    result=dict(scientific_acceptance=False)
    audit.evaluate(p,canonical(output(p)),tmp_path/'evaluated',result)
    captured=json.loads(rr.checked(result['source_audit']).read_bytes())
    assert len(captured['records'])==len(p['selected'])
    assert not result['scientific_acceptance']
    for row in captured['records']:
        assert row['verdict']=='indeterminate'
        for e in row['source_evidence']:
            b=next(b for b in p['bundle'].blocks if b.id==e['block_id'])
            assert b.text[e['start_char']:e['end_char']]==e['quote']


def test_missing_decisions_and_invented_or_duplicate_source_ids_are_rejected(prepared,tmp_path):
    _,p=prepared;good=output(p);rid=next(iter(good['decisions']))
    bad=deepcopy(good);bad['decisions'].pop(rid)
    with pytest.raises(ValueError,match='output_schema'):audit.evaluate(p,canonical(bad),tmp_path,{})
    bad=deepcopy(good);bad['decisions'][rid]['evidence_ids']=['invented']
    with pytest.raises(ValueError,match='output_schema'):audit.evaluate(p,canonical(bad),tmp_path,{})
    bad=deepcopy(good);key=bad['decisions'][rid]['evidence_ids'][0]
    bad['decisions'][rid]['evidence_ids']=[key,key]
    with pytest.raises(ValueError,match='duplicate_or_empty'):audit.evaluate(p,canonical(bad),tmp_path,{})


def test_finite_runner_replays_without_a_second_model_call(prepared,tmp_path):
    path,p=prepared
    class Provider:
        calls=0
        def extract(self,prompt,schema,config,directory):
            self.calls+=1
            assert prompt==p['prompt']
            return ProviderResult(canonical(output(p)),{},'codex','gpt-6-luna','test-response',0.01)
    provider=Provider();store=Store(tmp_path/'queue');job=audit.enqueue(store,path)
    first=audit.run(store,job,provider_override=provider)
    second=audit.run(store,job,provider_override=provider)
    assert first==second and provider.calls==1
    assert first['state']=='succeeded'
    assert not first['scientific_acceptance'] and not first['production_writes']
    assert not first['paper_completed'] and not first['ml_training_eligible']
