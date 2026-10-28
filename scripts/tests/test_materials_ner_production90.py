"""Admission decisions must not turn unknowns or changed evidence into passes."""
from copy import deepcopy
import hashlib
import json
import pytest
from materials_ner_production90 import digest, freeze_sample, qualify


@pytest.fixture
def audited(tmp_path):
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'blocks':[{'id':'B1','text':'Tc is 3.2 K.'}]}))
    pin={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    rows=[dict(work_id='arxiv:0000.00001',result_id=str(i),amendment_id='a',status='eligible_for_source_audit') for i in range(10)]
    selection=freeze_sample(rows,seed='test')
    audit=dict(selection_sha256=selection['selection_sha256'],reviewer_kind='model',records=[dict(r,
        verdict='correct',rationale='Synthetic admission-control fixture, not scientific evidence.',
        source_evidence=[dict(original_source=pin,block_id='B1',start_char=0,end_char=12,quote='Tc is 3.2 K.')]) for r in selection['records']])
    return selection,audit,source


def test_ninety_percent_passes_without_confidence_lower_bound_gate(audited):
    selection,audit,_=audited
    audit['records'][0]['verdict']='incorrect'
    report=qualify(selection,audit)
    assert report['qualified'] and report['observed_precision']==0.9
    assert report['wilson_95'][0]<0.9


def test_unknowns_are_not_correct_and_sample_cannot_shrink(audited):
    selection,audit,_=audited
    for row in audit['records'][:2]:row['verdict']='indeterminate'
    report=qualify(selection,audit)
    assert not report['qualified'] and report['indeterminate']==2
    audit['records'].pop()
    with pytest.raises(ValueError,match='frozen_sample'):qualify(selection,audit)


def test_changed_original_and_fabricated_quote_refuse_admission(audited):
    selection,audit,source=audited
    bad=deepcopy(audit);bad['records'][0]['source_evidence'][0]['quote']='Tc is 4.2 K.'
    with pytest.raises(ValueError,match='quote_mismatch'):qualify(selection,bad)
    source.write_text('{}')
    with pytest.raises(ValueError,match='input_changed'):qualify(selection,audit)
