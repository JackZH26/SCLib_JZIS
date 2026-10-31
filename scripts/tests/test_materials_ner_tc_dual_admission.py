"""Focused policy checks; generated examples are not scientific ground truth."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ingestion.materials_ner.reviewed_reader import reference
from materials_ner_production90 import digest, qualify
from materials_ner_tc_sampling import random_draw, retained, verify, RECORD_ROUTE
from materials_ner_tc_intake import admission_quality, checked_projection, prepare, AdmissionValidation


def population(n=500):
    return [dict(work_id=f'arxiv:paper{i}',result_id='r1',run_id=f'run{i}',
        projection_sha256=f'projection{i}',status='eligible_for_source_audit',holds=[]) for i in range(n)]


def test_random_window_has_fifty_checks_even_with_five_hundred_papers():
    rows=population()
    design=random_draw(rows,'registered-before-verdicts')
    assert len(design['records'])==50
    assert design==random_draw(list(reversed(rows)),'registered-before-verdicts')
    selection=dict(population=rows,seed='registered-before-verdicts',**design)
    assert verify(selection)==design
    selection['records'].pop()
    with pytest.raises(ValueError,match='plan_changed'):verify(selection)


def test_ninety_percent_uses_all_fifty_random_outcomes_and_known_errors_stay_out(tmp_path):
    source=tmp_path/'source.json';source.write_text(json.dumps(dict(blocks=[dict(id='b',text='Test evidence.')])) )
    rows=population();selection=dict(schema='materials-native-tc-sample/1',population=rows,
        seed='prospective',**random_draw(rows,'prospective'))
    selection['selection_sha256']=digest(selection)
    evidence=dict(original_source=reference(source),block_id='b',start_char=0,end_char=14,quote='Test evidence.')
    audit=dict(selection_sha256=selection['selection_sha256'],reviewer_kind='model',records=[
        dict(**row,verdict='correct' if i<45 else 'indeterminate',review_completed=i<45,
             rationale='Synthetic policy fixture.',source_evidence=[evidence])
        for i,row in enumerate(selection['records'])])
    q=qualify(selection,audit)
    assert q['sample_size']==50 and q['observed_precision']==0.9 and q['qualified']
    selected=[];individual=[]
    for row in rows:
        projection=dict(projection_sha256=row['projection_sha256'],records=[row])
        selected.extend(retained(projection,selection,audit))
        individual.extend(retained(projection,selection,audit,admission_route=RECORD_ROUTE))
    assert len(selected)==495 and len(individual)==45
    audit['records'][44]['verdict']='incorrect'
    assert not qualify(selection,audit)['qualified']


def test_individual_route_keeps_failed_batch_score_and_checks_original_decision(tmp_path,monkeypatch):
    import materials_ner_tc_intake as intake
    original=dict(work_id='arxiv:fixture',result_id='r1',run_id='run',projection_sha256='projection',
        verdict='correct',review_completed=True,rationale='Synthetic checked result.',source_evidence=[{'quote':'test'}])
    receipt=tmp_path/'decisions.json';receipt.write_text(json.dumps(dict(reviewer_kind='model',records=[original])))
    audit=dict(records=[dict(original,source_audit_receipt=reference(receipt))])
    failed_report=dict(qualified=False,observed_precision=0.8)
    monkeypatch.setattr(intake,'quality',lambda selection,audit:deepcopy(failed_report))
    assert admission_quality({},audit,RECORD_ROUTE)==failed_report
    with pytest.raises(ValueError,match='below_threshold'):admission_quality({},audit)
    changed=deepcopy(audit);changed['records'][0]['rationale']='Rewritten after review'
    with pytest.raises(ValueError,match='verdict_changed'):admission_quality({},changed,RECORD_ROUTE)
    changed=deepcopy(audit);changed['records'][0]['review_completed']=False
    with pytest.raises(ValueError,match='no_individually'):admission_quality({},changed,RECORD_ROUTE)
    changed=deepcopy(audit);del changed['records'][0]['source_audit_receipt']
    with pytest.raises(ValueError,match='receipt_required'):admission_quality({},changed,RECORD_ROUTE)


def test_validation_is_bound_to_unchanged_selection_audit_and_route():
    s=dict(records=[]);s['selection_sha256']=digest(s);a=dict(records=[])
    v=AdmissionValidation(s['selection_sha256'],digest(a),RECORD_ROUTE,json.dumps(dict(qualified=False)))
    assert v.report(s,a,RECORD_ROUTE)==dict(qualified=False)
    for selection,audit,route in [({**s,'records':['changed']},a,RECORD_ROUTE),
            (s,{'records':['changed']},RECORD_ROUTE),(s,a,'qualified_batch')]:
        with pytest.raises(ValueError,match='scope_changed'):v.report(selection,audit,route)


def test_actual_failed_luna_batch_can_plan_only_original_correct_records():
    path=os.environ.get('MATERIALS_P90_INDIVIDUAL_BATCH')
    if not path:pytest.skip('Set an actual failed Luna batch for read-only source replay')
    batch=Path(path);selection=json.loads((batch/'FROZEN_SAMPLE.json').read_bytes())
    audit=json.loads((batch/'luna-audit/SOURCE_AUDIT.json').read_bytes());before=deepcopy((selection,audit))
    report=admission_quality(selection,audit,RECORD_ROUTE)
    assert not report['qualified'] and report['observed_precision']<0.9
    for entry in selection['source_entries']:
        packet,projection=checked_projection(entry)
        chosen=retained(projection,selection,audit,admission_route=RECORD_ROUTE)
        if not chosen:continue
        anchor=lambda key:dict(id=key,row_sha256='0'*64)
        bindings=dict(purpose='pending_candidates',paper=anchor(packet['work_id']),
            work=anchor('00000000-0000-0000-0000-000000000001'),
            snapshot=anchor('00000000-0000-0000-0000-000000000002'),
            samples={r['graph']['samples'][0]['id']:anchor('source:test-'+r['result_id']) for r in chosen})
        plan=prepare(entry,bindings=bindings,captured_at='2026-10-28T00:00:00+00:00',
            selection=selection,audit=audit,admission_route=RECORD_ROUTE)
        assert len(plan['results'])==len(chosen)
        for claim in plan['rows']['material_claims']:
            status=claim['extraction_metadata']['production_admission']
            assert status['admission_route']==RECORD_ROUTE and status['per_record_checked']
            assert not status['batch_qualified'] and not status['independent_expert_review']
        break
    else:pytest.fail('Actual failed batch has no correct results')
    assert (selection,audit)==before
