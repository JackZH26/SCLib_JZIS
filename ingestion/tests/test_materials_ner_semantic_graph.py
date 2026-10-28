"""Scientific-relation failure modes, not independent scientific validation."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner import semantic_graph as flow
from ingestion.materials_ner.contract import canonical, digest, parse_extraction
from ingestion.materials_ner.proposals import ProposalDatabase, review_rows, verify_packet
from ingestion.materials_ner.sources import sha
from test_materials_ner_source_choice_graph import fixture, selection


def semantic_selection(bundle, base, request):
    old = selection(bundle, base, request); assertions = {}
    for aid, s in old['assertions'].items():
        c = s['state']['conditions'][0]
        assertions[aid] = dict(outcome='append', name=s['name_candidate_id'], quantity_kind='tc',
            origin='observed', source_role='primary', claim_support=['C1'], attribution_support=['C1'],
            sample='S1', sample_support=['C1'], sample_link_reason='The source names this crystal.',
            method=None, method_class='unspecified', criterion='unspecified', criterion_text=None,
            cited_source=None, conditions_complete=True, unrepresented_context=False,
            conditions=[dict(kind=c['kind'], number=c['quantity_occurrence_id'], role='measurement',
                direction=c['orientation_candidate_id'], basis=c['basis_candidate_id'], support=['C1'])])
    return dict(schema_version=flow.POLICY, work_id=bundle.work_id, assertions=assertions, limitations=[])


def test_compilation_preserves_original_scientific_choices_and_missingness(tmp_path):
    b, base, r = fixture(tmp_path); before = base.model_dump(); output = semantic_selection(b, base, r)
    jsonschema.Draft202012Validator.check_schema(flow.output_schema(b, base, r))
    p, v = flow.project(flow.parse(canonical(output), b, base, r), b, base, r)
    assert v['appended_results'] == 2 and v['held_targets'] == 0
    assert base.model_dump() == before and p['existing_entities_unchanged']
    g = parse_extraction(p['graph'])
    assert [(x.quantity.value, g.states[i].conditions[0].quantity.value) for i,x in enumerate(g.results)] == [(20,9),(12,26.42)]
    assert all(c.kind == 'reported_magnetic_field' and c.basis_raw == '$H$' for s in g.states for c in s.conditions)
    assert all(x.method is None and x.method_class == 'unspecified' for x in g.protocols)
    assert all(x.definition.criterion == 'unspecified' for x in g.results)
    assert all(c.kind != 'pressure' for s in g.states for c in s.conditions)
    assert not [i for i in v['native']['issues'] if i['path'].startswith(('/states/', '/results/', '/protocols/'))]
    assert not v['scientific_acceptance'] and not v['qualified_ml_rows']


@pytest.mark.parametrize('change', ['incomplete_conditions','extra_context','computed','derived','non_detection'])
def test_unsupported_context_is_held_not_silently_dropped(tmp_path, change):
    b, base, r = fixture(tmp_path); output = semantic_selection(b, base, r); a = output['assertions']['A1']
    if change == 'incomplete_conditions': a['conditions_complete'] = False
    elif change == 'extra_context': a['unrepresented_context'] = True
    elif change == 'non_detection': a['quantity_kind'] = 'non_detection'
    else: a['origin'] = {'computed':'computed','derived':'model_derived'}[change]
    p, v = flow.project(flow.parse(canonical(output), b, base, r), b, base, r)
    assert v['appended_results'] == 1 and p['holds'][0]['assertion_id'] == 'A1'
    assert 'requires_full_graph_stage' in p['holds'][0]['reason']


@pytest.mark.parametrize('change,error', [
    ('method','semantic_method_missingness_mismatch'),
    ('criterion','semantic_criterion_missingness_mismatch'),
    ('citation','semantic_citation_missingness_mismatch'),
    ('field_unit','semantic_condition_unit_mismatch'),
    ('field_basis','semantic_reported_field_basis_required')])
def test_known_false_defaults_and_field_conversion_rejected(tmp_path, change, error):
    b, base, r = fixture(tmp_path); output = semantic_selection(b, base, r); a = output['assertions']['A1']
    if change == 'method': a['method_class'] = 'resistivity'
    elif change == 'criterion': a['criterion'] = 'zero_resistance'
    elif change == 'citation': a['source_role'] = 'cited'
    elif change == 'field_unit': a['conditions'][0]['kind'] = 'temperature'
    else: a['conditions'][0]['basis'] = None
    with pytest.raises(ValueError, match=error): flow.project(flow.parse(canonical(output),b,base,r),b,base,r)


@pytest.mark.parametrize('change', ['sample','span','name','duplicate_key'])
def test_unknown_identity_and_duplicate_keys_rejected(tmp_path, change):
    b, base, r = fixture(tmp_path); output = semantic_selection(b,base,r); a = output['assertions']['A1']
    if change == 'sample': a['sample'] = 'S999'
    elif change == 'span': a['sample_support'] = ['C999']
    elif change == 'name': a['name'] = 'invented Tc'
    raw = canonical(output)
    if change == 'duplicate_key': raw = raw.replace('"work_id":', '"work_id":"duplicate","work_id":')
    with pytest.raises((ValueError,jsonschema.ValidationError)): flow.parse(raw,b,base,r)


def packet(tmp_path):
    b, base, r = fixture(tmp_path); raw = canonical(semantic_selection(b,base,r))
    p,v = flow.project(flow.parse(raw,b,base,r),b,base,r)
    receipt = dict(work_id=b.work_id,bundle_sha256=digest(b.model_dump()),state='quarantined',
        raw_output_sha256=sha(raw.encode()),extraction=p['graph'],validation=v['native'],
        semantic_base_graph=base.model_dump(),semantic_request=r,
        semantic_audit={k:v for k,v in p.items() if k!='graph'},scientific_acceptance=False,
        config=dict(output_format=flow.POLICY,model='synthetic-test',request_sha256=digest(r),
            schema_sha256=digest(flow.output_schema(b,base,r)),prompt_sha256=sha(flow.render(b,base,r).encode())))
    result = dict(schema='materials-ner-proposals/2',job_id='synthetic',run_id=digest(receipt),
        work_id=b.work_id,bundle_hash=digest(b.model_dump()),bundle=b.model_dump(),receipt=receipt,
        raw_output=raw,rows=review_rows(parse_extraction(p['graph']),v['native']),evidence=v['native']['resolved_evidence'],
        scientific_acceptance=False,ml_training_eligible=False)
    result['packet_hash']=digest(result)
    return result


def test_replay_and_idempotent_storage(tmp_path):
    p=packet(tmp_path);verify_packet(p);db=ProposalDatabase(tmp_path/'proposals')
    assert db.ingest(p)['inserted'] and not db.ingest(p)['inserted']
    with db.connect() as c:
        rows=[json.loads(r['payload']) for r in c.execute('SELECT payload FROM conditions')]
    assert [r['quantity']['value'] for r in rows]==[9,26.42]


def test_rehashed_packet_cannot_change_pairing_behind_model_output(tmp_path):
    p=packet(tmp_path)
    p['receipt']['extraction']['states'][0]['conditions'][0]['quantity']['value']=26.42
    p['run_id']=digest(p['receipt']);p['packet_hash']=digest({k:v for k,v in p.items() if k!='packet_hash'})
    with pytest.raises(ValueError,match='semantic_receipt_graph_mismatch'): verify_packet(p)


def test_all_held_has_no_scientific_changes(tmp_path):
    b,base,r=fixture(tmp_path)
    output=dict(schema_version=flow.POLICY,work_id=b.work_id,assertions={x['assertion_id']:
        dict(outcome='held',reason='Unresolved source ownership.') for x in r['records']},limitations=[])
    p,v=flow.project(flow.parse(canonical(output),b,base,r),b,base,r)
    assert p['graph']==dict(base.model_dump(),schema_version='materials-ner/10') and v['held_targets']==2


def test_prompt_contains_original_view_and_no_graph_pointer_burden(tmp_path):
    b,base,r=fixture(tmp_path);prompt=flow.render(b,base,r)
    assert b.blocks[0].text in prompt.replace('\\\\','\\')
    assert '26.42 T' in prompt and 'name_ids' in prompt
    assert '/conditions/0' not in prompt and 'EXISTING SAMPLES' in prompt


def test_unknown_source_view_policy_cannot_silently_change_frozen_input(tmp_path):
    b,base,r=fixture(tmp_path);r['semantic_view_policy']='unknown'
    with pytest.raises(ValueError,match='semantic_source_view_policy_unknown'): flow.render(b,base,r)
