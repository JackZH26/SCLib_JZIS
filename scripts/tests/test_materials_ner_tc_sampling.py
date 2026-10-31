"""Sampling/admission-policy tests; generated rows are not scientific examples."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from materials_ner_production90 import digest, qualify
from materials_ner_tc_sampling import draw, verify, weighted_precision, retained


def population(sizes):
    return [dict(work_id=f'arxiv:paper{h}',result_id=f'r{i}',run_id=f'run{h}',
        projection_sha256=f'projection{h}',status='eligible_for_source_audit',holds=[])
        for h,size in enumerate(sizes) for i in range(size)]


def selection(rows,seed='frozen-before-audit'):
    return dict(seed=seed,population=rows,**draw(rows,seed))


def test_sampling_is_frozen_balanced_and_not_a_fifty_row_ceiling():
    rows=population([80,15,5]);s=selection(rows)
    assert len(s['records'])==50 and len(s['strata'])==3
    assert all(x['sample_size']>=1 for x in s['strata'])
    assert draw(list(reversed(rows)),s['seed'])==draw(rows,s['seed'])
    assert verify(s)['records']==s['records']
    changed=deepcopy(s);changed['strata'][0]['population_size']+=1
    with pytest.raises(ValueError,match='plan_changed'):verify(changed)


def test_unknowns_count_as_errors_and_population_weights_are_used():
    s=selection(population([90,9,1]))
    audit=[dict(**r,verdict='correct' if r['work_id']=='arxiv:paper0' else 'indeterminate') for r in s['records']]
    assert weighted_precision(s,audit)==0.9
    projection=dict(projection_sha256='projection0',records=[r for r in s['population'] if r['work_id']=='arxiv:paper0'])
    one=next(r for r in audit if r['work_id']=='arxiv:paper0');one['verdict']='incorrect'
    admitted=retained(projection,s,dict(records=audit))
    assert len(admitted)==89 and one['result_id'] not in {r['result_id'] for r in admitted}
    assert len(admitted)>len([r for r in audit if r['verdict']=='correct'])
    census={**s,'method':'census_of_retained_records'}
    assert len(retained(projection,census,dict(records=audit)))==len([r for r in audit if r['verdict']=='correct'])


def test_quality_uses_ninety_percent_weighted_point_without_interval_gate(tmp_path):
    source=tmp_path/'source.json';source.write_text(json.dumps(dict(blocks=[dict(id='b',text='Synthetic test source.')])) )
    from ingestion.materials_ner.reviewed_reader import reference
    s=selection(population([90,9,1]));s['schema']='materials-native-tc-sample/1';s['selection_sha256']=digest(s)
    evidence=dict(original_source=reference(source),block_id='b',start_char=0,end_char=22,quote='Synthetic test source.')
    records=[dict(**r,verdict='correct' if r['work_id']=='arxiv:paper0' else 'indeterminate',
        rationale='Synthetic policy test, not scientific validation.',source_evidence=[evidence]) for r in s['records']]
    audit=dict(selection_sha256=s['selection_sha256'],reviewer_kind='model',records=records)
    q=qualify(s,audit)
    assert q['observed_precision']==0.9 and q['qualified']
    assert q['population_confidence_interval_95'] is None
    assert q['wilson_95_scope'].startswith('Unweighted')
    del audit['records'][0]
    with pytest.raises(ValueError,match='frozen_sample'):qualify(s,audit)


def test_unsampled_real_source_plan_has_no_false_per_record_review():
    root=os.environ.get('MATERIALS_P90_CORE_BATCH')
    if not root:pytest.skip('Requires a pinned actual core-output batch; no database writes.')
    from materials_ner_tc_intake import freeze, prepare
    b=Path(root);original=json.loads((b/'FROZEN_SAMPLE_CORE_V3.json').read_bytes())
    entry=next(e for e in original['source_entries'] if 'cond-mat_0604354' in e['packet']['path'])
    s=freeze([entry],seed='synthetic-policy-test-on-authentic-source-packet')
    # Exercise the unsampled branch on two real, already captured results.
    # The production freeze default remains a census for populations <= 50.
    s.update(draw([r for r in s['population'] if r['status']=='eligible_for_source_audit'],s['seed'],limit=1))
    s['selection_sha256']=digest({k:v for k,v in s.items() if k!='selection_sha256'})
    audit=json.loads((b/'SOURCE_AUDIT_CORE_V3.json').read_bytes());audit['selection_sha256']=s['selection_sha256']
    audit['records']=[r for r in audit['records'] if any(all(r[k]==x[k] for k in ('work_id','result_id','run_id','projection_sha256')) for x in s['records'])]
    saved=json.loads((b/'admission-core-v3/cond-mat_0604354/PLAN.json').read_bytes())
    at=json.loads((b/'admission-core-v3/EPOCH.json').read_bytes())['captured_at']
    plan=prepare(entry,bindings=saved['bindings'],captured_at=at,selection=s,audit=audit)
    states=[c['extraction_metadata']['production_admission'] for c in plan['rows']['material_claims']]
    assert len(states)==2 and sum(x['per_record_checked'] for x in states)==1
    assert {x['quality_status'] for x in states}=={'model_source_checked','batch_sampled'}
    assert all(not x['independent_expert_review'] for x in states)
