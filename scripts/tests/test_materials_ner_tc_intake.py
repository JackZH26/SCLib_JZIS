"""Replay a pinned actual Luna tranche without model or database calls.

Set MATERIALS_P90_TEST_BATCH to the captured batch-002 directory.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ingestion.materials_ner import reviewed_reader as rr
from ingestion.materials_ner.proposals import verify_packet
from materials_ner_tc_projection import project
from materials_ner_tc_intake import canonical_method, checked_projection, quality


@pytest.fixture
def batch():
    path=os.environ.get('MATERIALS_P90_TEST_BATCH')
    if not path:pytest.skip('Requires an explicitly selected actual Luna batch')
    return Path(path)


def load(path):return json.loads(path.read_bytes())


def test_missing_optional_method_does_not_invent_a_literal_or_mutate_extraction():
    protocol=dict(method_class='resistivity',method=None,evidence=[dict(
        block_id='b',start_char=0,quote='Resistance falls at the transition.')])
    packet=dict(run_id='run',bundle=dict(blocks=[]))
    before=deepcopy((packet,protocol))
    method,raw,evidence,omissions=canonical_method(packet,protocol,'r1',{'records':[]})
    assert (method,raw,evidence)==('unspecified',None,[])
    assert omissions[0]['before']=='resistivity'
    assert omissions[0]['reason']=='optional_method_without_source_bound_literal'
    assert (packet,protocol)==before


def test_method_binding_checks_original_bytes_and_only_uses_correct_same_record_audit():
    import hashlib
    text='The resistivity decreases.'
    witness=dict(block_id='b',start_char=0,quote=text)
    packet=dict(run_id='run',bundle=dict(blocks=[dict(id='b',text=text,document_id='doc',
        sha256=hashlib.sha256(text.encode()).hexdigest(),locator='pdf_page:1')]))
    protocol=dict(method_class='resistivity',method=None,evidence=[])
    row=dict(run_id='run',result_id='r1',verdict='correct',source_evidence=[witness])
    method,raw,evidence,omissions=canonical_method(packet,protocol,'r1',{'records':[row]})
    assert (method,raw,omissions)==('resistivity','resistivity',[])
    assert text[evidence[0]['start_char']:evidence[0]['end_char']]=='resistivity'
    for change in [{'run_id':'another-run'},{'result_id':'r2'},{'verdict':'incorrect'}]:
        assert canonical_method(packet,protocol,'r1',{'records':[{**row,**change}]})[0]=='unspecified'
    changed=deepcopy(packet);changed['bundle']['blocks'][0]['text']='The magnetism decreases.'
    with pytest.raises(ValueError,match='method_rebinding_mismatch'):
        canonical_method(changed,protocol,'r1',{'records':[row]})


def test_invalid_secondary_results_do_not_quarantine_primary_and_values_do_not_change(batch):
    packet=load(batch/'2107.06596/PACKET.json');original=deepcopy(packet)
    verify_packet(packet)
    assert 'extraction' not in packet['receipt']
    projection=project(packet);assert packet==original
    retained=[r for r in projection['records'] if r['status']=='eligible_for_source_audit']
    assert len(retained)==1 and len(projection['records'])==3
    raw=next(r for r in json.loads(packet['raw_output'])['results'] if r['id']==retained[0]['result_id'])
    assert retained[0]['graph']['results'][0]['quantity']==raw['quantity']
    assert retained[0]['graph']['samples'][0]['composition_basis']=='unresolved'
    assert all(r['holds']==['outside_initial_primary_experimental_scope'] for r in projection['records'] if r not in retained)


def test_optional_prose_omission_preserves_measured_field_and_criterion(batch):
    p=project(load(batch/'1907.04718/PACKET.json'));g=p['records'][0]['graph']
    assert p['records'][0]['status']=='eligible_for_source_audit'
    assert g['protocols'][0]['details_raw'] is None
    assert g['states'][0]['conditions'][0]['quantity']['value']==1
    assert g['states'][0]['conditions'][0]['quantity']['unit']=='mT'
    assert g['states'][0]['conditions'][0]['orientation_raw']=='along the c axis'
    assert g['results'][0]['definition']['criterion']=='onset'
    assert g['states'][0]['pressure']['regime']=='unknown'


def test_rehashing_changed_projection_does_not_make_it_authentic(batch,tmp_path):
    s=load(batch/'FROZEN_SAMPLE_V2.json');entry=next(e for e in s['source_entries'] if '2107.06596' in e['packet']['path'])
    changed=load(Path(entry['projection']['path']));changed['records'][0]['graph']['results'][0]['quantity']['value']=999
    path=tmp_path/'forged.json';path.write_text(json.dumps(changed))
    with pytest.raises(ValueError,match='projection_changed'):
        checked_projection({**entry,'projection':rr.reference(path)})


def test_known_bad_unknown_missing_or_wrong_source_cannot_pass(batch):
    s=load(batch/'FROZEN_SAMPLE_V2.json');a=load(batch/'SOURCE_AUDIT_V2.json')
    assert quality(s,a)['qualified']
    bad=deepcopy(a);bad['records'][0]['verdict']='indeterminate'
    assert not quality(s,bad)['qualified']
    bad=deepcopy(a);bad['records'].pop()
    with pytest.raises(ValueError,match='frozen_sample'):quality(s,bad)
    bad=deepcopy(a);bad['records'][0]['source_evidence']=deepcopy(bad['records'][1]['source_evidence'])
    with pytest.raises(ValueError,match='audit_source_not_from_run'):quality(s,bad)


def test_canonical_rebinding_is_literal_and_expert_state_remains_pending(batch):
    readback=load(batch/'admission/cond-mat_0010304/READBACK.json')
    claim=readback['readback']['material_claims'][0];meta=claim['extraction_metadata']
    assert claim['value_kelvin']==43 and claim['validity_status']=='pending'
    assert meta['result_semantics']['definition']['criterion_raw']=='transition onset'
    assert meta['native_origin']['canonical_literal_rebindings']
    assert meta['production_admission']['per_record_checked']
    assert not meta['production_admission']['independent_expert_review']


@pytest.fixture
def v4_recovery():
    root=os.environ.get('MATERIALS_P90_CORE_BATCH')
    if not root:pytest.skip('Requires an actual core batch and v4 recovery')
    path=Path(root).parent/'recovery-v4'
    if not (path/'SOURCE_AUDIT.json').exists():pytest.skip('Actual v4 audit not available')
    return path


def recovery_plan(path,work,excluded=()):
    from materials_ner_tc_intake import prepare
    s=load(path/'FROZEN_SAMPLE.json');a=load(path/'SOURCE_AUDIT.json')
    e=next(e for e in s['source_entries'] if work in e['packet']['path'])
    previous=load(path/'admission'/work/'PLAN.json')
    return prepare(e,bindings=previous['bindings'],captured_at=load(path/'admission/EPOCH.json')['captured_at'],
        selection=s,audit=a,excluded_result_ids=excluded),e


def test_new_projection_plan_keeps_only_new_provider_results(v4_recovery):
    plan,_=recovery_plan(v4_recovery,'cond-mat_0102023',{'r6'})
    assert {r['source_result_id'] for r in plan['results']}=={'r1','r2','r3','r4','r5'}
    assert [r['value_kelvin'] for r in plan['rows']['material_claims']]==[45,65,70,72,72]
    assert len({r['id'] for r in plan['rows']['research_samples']})==5
    with pytest.raises(ValueError,match='sample_bindings_required'):
        recovery_plan(v4_recovery,'cond-mat_0102023')


def test_required_method_word_rebinds_to_actual_original_evidence(v4_recovery):
    plan,e=recovery_plan(v4_recovery,'1901.05693')
    assert plan['rows']['research_protocols'][0]['method_raw']=='resistivity'
    claim=plan['rows']['material_claims'][0]
    link=next(x for x in claim['extraction_metadata']['native_origin']['canonical_literal_rebindings']
        if x['path']=='/protocols/0/method')
    packet=load(Path(e['packet']['path']));block=next(b for b in packet['bundle']['blocks'] if b['id']==link['block_id'])
    assert block['text'][link['start_char']:link['end_char']]=='resistivity'
    assert claim['value_kelvin']==39 and claim['tc_definition']=='onset'
