"""Authored source-role and handoff regressions; zero scientific dataset rows."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner import source_role_inventory as role,typed_inventory_handoff as handoff,frozen_inventory
from ingestion.materials_ner.contract import canonical,digest
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.numeric_occurrences import source_candidates
from ingestion.materials_ner.proposals import ProposalDatabase,import_packet,verify_packet
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from ingestion.materials_ner import item_worker
from test_materials_ner_typed_inventory import inputs
from test_materials_ner_item_stages import StageProvider,responses


def fixture():
    original,model,catalog,decisions,links=inputs()
    bundle,scope=role.scope(original,[b.id for b in original.blocks]);cat=role.catalog(bundle)
    names=['onset','zero resistance','total thickness','total thickness','supercurrent'];claims=[];bindings={}
    for n,e in enumerate(model.entries):
        numeric=e.type=='numeric_result'
        candidate=next((k for k,v in cat['numeric_candidates'].items() if v['quote']==e.value_raw),None) if numeric else None
        claim=dict(role='numeric_result' if numeric else 'unvalued_result',sample_description=e.sample_description,
            property_name=dict(span_ids=e.source_span_ids,quote=names[n]),
            subject_evidence=[dict(span_ids=e.source_span_ids,quote='Sample A')],support_span_ids=e.source_span_ids,
            numeric_candidate_id=candidate,statement=None if numeric else dict(span_ids=e.source_span_ids,quote=e.statement_raw),
            value_status=None if numeric else e.value_status,context_kind='protocol',description=e.quantity_description)
        claims.append(claim);bindings[f'A{n+1}']=dict(decision='emit',quantity_kind=e.quantity_kind,
            attribution=e.attribution.model_dump(),kind_reason='Authored source property and measurement.',unresolved_reason=None)
    for c in model.context_assertions:
        claims.append(dict(role='context',sample_description='Sample A',property_name=None,subject_evidence=[],
            support_span_ids=c.span_ids,numeric_candidate_id=None,statement=None,value_status=None,
            context_kind=c.kind,description=c.description))
    plan=role.RolePlan(schema_version=role.ROLE_VERSION,work_id=bundle.work_id,catalog_sha256=cat['catalog_sha256'],
        claims=claims,span_assessments=model.span_assessments,unread_block_ids=[],limitations=[])
    binding=role.Bindings(schema_version=role.BINDING_VERSION,work_id=bundle.work_id,
        plan_sha256=digest(plan.model_dump()),decisions=bindings)
    return original,bundle,scope,plan,binding,catalog,decisions,links


def snapshot():
    original,bundle,scope,plan,binding,*rest=fixture()
    typed,inventory,proof=role.compile_inventory(plan,binding,bundle)
    captures=dict(original_bundle=canonical(original.model_dump()),source_bundle=canonical(bundle.model_dump()),
        source_catalog=canonical(source_catalog(bundle)),scope=canonical(scope),numeric_catalog=canonical(role.catalog(bundle)),source_layout='null',
        role_prompt=role.render_roles(original,bundle,scope),role_schema=canonical(role.role_schema(bundle)),
        role_raw=canonical(plan.model_dump()),role_plan=canonical(plan.model_dump()),role_validation=canonical(proof['role_validation']),
        binding_prompt=role.render_bindings(original,bundle,scope,plan),binding_schema=canonical(role.binding_schema(bundle,plan)),
        binding_raw=canonical(binding.model_dump()),bindings=canonical(binding.model_dump()),typed_inventory=canonical(typed.model_dump()),
        validation=canonical(proof['typed_projection']['validation']),projection=canonical(proof),inventory=canonical(inventory.model_dump()))
    receipt=dict(schema=role.ATTEMPT,work_id=bundle.work_id,status='source_role_inventory_valid',provider_calls=2,
        terminal=True,source_unchanged=True,scientific_acceptance=False,full_graph_extraction=False,
        model='authored-test-only',item_count=len(inventory.items),
        **{k:dict(path='/authored/'+k,sha256=sha(v.encode())) for k,v in captures.items()})
    parent=handoff.build(bundle,receipt_raw=canonical(receipt),captures=captures)
    return bundle,parent,receipt,captures,rest


def test_source_numbers_and_named_multiplicity_survive_both_stage_schemas():
    original,bundle,scope,plan,binding,*_=fixture()
    jsonschema.validate(plan.model_dump(),role.role_schema(bundle))
    jsonschema.validate(binding.model_dump(),role.binding_schema(bundle,plan))
    typed,inventory,proof=role.compile_inventory(plan,binding,bundle)
    assert [e.value_raw for e in typed.entries[:-1]]==['39 K','37 K','8 nm','8 nm']
    assert typed.entries[-1].type=='unvalued_result' and inventory.items[-1].value_raw is None
    assert proof['typed_projection']['validation']['valid'] and not proof['scientific_acceptance']
    assert [b.text for b in bundle.blocks]==[b.text for b in original.blocks]
    assert scope['original_block_count']==scope['target_block_count']==1
    assert not scope['full_source_coverage_established']
    assert len(proof['mapping'])==5


@pytest.mark.parametrize('variant',['missing_read','unread','changed_catalog','bad_property','duplicate_support','numeric_as_unvalued','missing_value','missing_property','context_status'])
def test_invalid_roles_never_reach_binding_or_compilation(variant):
    _,b,_,p,_,*_=fixture()
    if variant=='missing_read':p.span_assessments.clear()
    elif variant=='unread':p.unread_block_ids=['B1']
    elif variant=='changed_catalog':p.catalog_sha256='0'*64
    elif variant=='bad_property':p.claims[0].property_name.quote='fabricated physical property'
    elif variant=='duplicate_support':p.claims[0].support_span_ids*=2
    elif variant=='numeric_as_unvalued':p.claims[0].role='unvalued_result'
    elif variant=='missing_value':p.claims[0].numeric_candidate_id=None
    elif variant=='missing_property':p.claims[0].property_name=None
    else:p.claims[-1].value_status='explicit_non_detection'
    assert not role.inspect_plan(p,b)['valid']
    with pytest.raises(ValueError,match='role_plan_not_valid'):role.binding_schema(b,p)


@pytest.mark.parametrize('variant',['missing','extra','changed_plan','wrong_kind','disconnected_origin','missing_origin','unmapped_no_reason'])
def test_binding_cannot_change_or_silently_drop_source_claims(variant):
    _,b,_,p,v,*_=fixture()
    if variant=='missing':v.decisions.pop('A1')
    elif variant=='extra':v.decisions['A999']=v.decisions['A1']
    elif variant=='changed_plan':v.plan_sha256='0'*64
    elif variant=='wrong_kind':v.decisions['A1'].quantity_kind='critical_pressure'
    elif variant=='disconnected_origin':v.decisions['A1'].attribution.span_ids=['S999']
    elif variant=='missing_origin':v.decisions['A1'].attribution.span_ids=[]
    else:v.decisions['A1'].quantity_kind='unmapped'
    with pytest.raises(ValueError):role.compile_inventory(p,v,b)


def test_held_outcome_remains_a_scientific_obligation_without_fabricated_value():
    _,b,_,p,v,*_=fixture();v.decisions['A1']=role.Hold(decision='hold',reason='Source ownership unresolved.',span_ids=['S1'])
    typed,inv,proof=role.compile_inventory(p,v,b)
    assert len(typed.entries)==4 and proof['held_outcomes'][0]['claim_id']=='A1'
    assert not proof['held_outcomes'][0]['scientific_exclusion_approved']
    assert any('Unresolved outcome A1' in c.description for c in typed.context_assertions)
    parent={'run_id':'authored','required_occurrences':[],
        'source_role_accounting':{'held_outcomes':proof['held_outcomes']}}
    outcome=handoff.outcome_accounting(parent,{})
    assert not outcome['fully_materialized'] and outcome['held_source_outcomes']


def test_undigitized_claim_compiles_to_unvalued_not_numeric_or_false_negative():
    _,b,_,p,_,*_=fixture();p.claims[-1].role='context'
    # Reuse the actual authored non-detection sentence as a transport fixture;
    # this test checks value preservation, not scientific interpretation.
    p.claims[4].value_status='figure_not_digitized'
    v=role.Bindings(schema_version=role.BINDING_VERSION,work_id=b.work_id,plan_sha256=digest(p.model_dump()),
        decisions={k:role.Emit(decision='emit',quantity_kind='tc' if k=='A5' else ('tc' if k in ['A1','A2'] else 'thickness'),
            attribution=dict(origin='observed',source_role='primary',span_ids=['S1']),kind_reason='Authored transport case.',unresolved_reason=None)
            for k in role.eligible(p)})
    typed,_,_=role.compile_inventory(p,v,b)
    assert typed.entries[-1].quantity_kind=='tc' and typed.entries[-1].value_status=='figure_not_digitized'
    assert not hasattr(typed.entries[-1],'value_raw')


@pytest.mark.parametrize('key',role.CAPTURE_KEYS)
def test_all_source_role_handoff_captures_are_hash_bound(key):
    b,_,receipt,captures,_=snapshot();captures[key]+=' '
    with pytest.raises(ValueError,match='source_role_capture_hash_mismatch'):
        handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


def test_rehashed_raw_and_scoped_source_rewrites_are_rejected():
    b,parent,receipt,captures,_=snapshot()
    changed=deepcopy(parent);changed['source_role_accounting']['held_outcomes']=[{'fabricated':True}]
    changed['run_id']=digest({k:v for k,v in changed.items() if k!='run_id'})
    with pytest.raises(ValueError,match='snapshot_mismatch'):frozen_inventory.verify(changed)
    captures['role_plan']=captures['role_plan'].replace('Sample A','rewritten specimen')
    receipt['role_plan']['sha256']=sha(captures['role_plan'].encode())
    with pytest.raises(ValueError,match='source_role_output_rewritten'):
        handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


@pytest.mark.parametrize('schema,status,code',[
    ('materials-typed-source-inventory-attempt/1','typed_inventory_invalid','typed_frozen_receipt_not_admissible'),
    (role.ATTEMPT,'role_plan_invalid','source_role_receipt_not_admissible')])
def test_actual_invalid_receipt_shape_is_rejected_before_missing_capture_access(tmp_path,schema,status,code):
    _,b,*_=fixture();p=tmp_path/'invalid.json'
    p.write_text(canonical(dict(schema=schema,status=status,terminal=True)))
    with pytest.raises(ValueError,match=code):frozen_inventory.from_files(b,p,None)


def test_real_worker_consumer_replay_and_private_import_accept_compiled_parent(tmp_path):
    b,parent,_,_,rest=snapshot();catalog,decisions,links=rest
    assert len(frozen_inventory.verify(parent).items)==5
    store=Store(tmp_path/'worker');job=item_worker.enqueue(store,parent,group_size=2)
    result=run_one(store,job_id=job,provider_override=StageProvider(responses(b,catalog,decisions,links)))
    assert result['state']=='succeeded',result
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['frozen_source_accounting']['materialized_items']==5
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


@pytest.mark.parametrize('raw,approximate,unit',[
    ('∼ 83%',True,'%'),('∼ 1.83 K',True,'K'),('≈\n−0.7(1) K GPa−1',True,'K GPa−1'),
    ('−1.9 K GPa−1',False,'K GPa−1'),('(300 ± 30) µΩ·cm',False,'µΩ·cm'),
    ('0.02 µΩ cm K −2',False,'µΩ cm K −2')])
def test_pdf_numeric_selection_preserves_approximation_and_complete_unit_exponents(raw,approximate,unit):
    legacy=source_candidates(raw);rows=source_candidates(raw,pdf_unicode=True)
    usable=[v for v in rows if v['quantity'] is not None]
    assert len(usable)==1
    row=usable[0];assert row['quote']==raw and row['evidence']['unit']['quote']==unit
    assert row['syntax_shape']['approximate']==approximate
    assert raw[row['start_char']:row['end_char']]==raw
    assert source_candidates(raw)==legacy


def test_context_page_numbers_never_enter_target_numeric_catalog():
    original,*_=inputs();extra=original.blocks[0].model_copy(update=dict(id='second',ordinal=1,text='Unrelated Tc = 999 K.',sha256=sha(b'Unrelated Tc = 999 K.')))
    original.blocks.append(extra)
    scoped,proof=role.scope(original,[original.blocks[0].id]);cat=role.catalog(scoped)
    assert all(v['block_id']!='second' for v in cat['numeric_candidates'].values())
    assert proof['original_block_count']==2 and proof['target_block_count']==1
    assert scoped.blocks[-1].text==original.blocks[-1].text


def selected_fixture():
    original,bundle,scope,old,bindings,*rest=fixture();cat=role.selection_catalog(bundle)
    source=source_catalog(bundle)
    def choose(phrase):
        if phrase is None:return None
        location=role.typed._literal_locations(source,phrase.span_ids,phrase.quote)[0]
        ids=role._text_ids_for(cat,location)
        return dict(first_text_id=ids[0],last_text_id=ids[-1] if len(ids)>1 else None)
    claims=[]
    for c in old.claims:
        support=[k for k,v in cat['texts'].items() if v['selectable'] and set(v['source_span_ids'])&set(c.support_span_ids)]
        row=dict(role=c.role,sample_description=c.sample_description,property_evidence=choose(c.property_name),
            subject_evidence=[choose(p) for p in c.subject_evidence],support_text_ids=support,
            context_kind=c.context_kind,description=c.description)
        if c.role=='numeric_result':row['numeric_candidate_id']=c.numeric_candidate_id
        elif c.role=='unvalued_result':row.update(statement=choose(c.statement),value_status=c.value_status)
        claims.append(row)
    p=role.SelectionPlan(schema_version=role.SELECTION_VERSION,work_id=bundle.work_id,catalog_sha256=cat['catalog_sha256'],
        claims=claims,text_assessments={},numeric_assessments={},unread_target_units=[],limitations=[])
    for key in cat['target_text_ids']:
        linked=[n for n,c in enumerate(p.claims,1) if key in role._selected_anchors(c,bundle,cat)]
        p.text_assessments[key]=role.TextAssessment(disposition='outcomes' if linked else 'context_only',
            claim_numbers=linked,reason='Authored source classification, not scientific approval.')
    for key in cat['numeric_obligation_ids']:
        linked=[n for n,c in enumerate(p.claims,1) if c.role=='numeric_result' and c.numeric_candidate_id==key]
        p.numeric_assessments[key]=role.NumericAssessment(disposition='outcome' if linked else 'condition',
            claim_numbers=linked,reason='Authored source classification, not scientific approval.')
    v=role.SelectionBindings(schema_version=role.SELECTION_BINDING,work_id=bundle.work_id,
        plan_sha256=digest(p.model_dump()),decisions=bindings.decisions,
        coverage_checks={k:dict(decision='non_outcome_supported',reason='Authored non-outcome classification.')
            for k in role.selected_coverage(p,cat)})
    return original,bundle,scope,p,v,rest


def selected_snapshot():
    original,b,scope,p,v,rest=selected_fixture();cat=role.selection_catalog(b)
    typed,inventory,proof=role.compile_selections(p,v,b)
    captures=dict(original_bundle=canonical(original.model_dump()),source_bundle=canonical(b.model_dump()),
        source_catalog=canonical(source_catalog(b)),scope=canonical(scope),numeric_catalog=canonical(role.catalog(b)),
        selection_catalog=canonical(cat),source_layout='null',role_prompt=role.render_selected_roles(original,b,scope),
        role_schema=canonical(role.selected_role_schema(b)),role_raw=canonical(p.model_dump()),role_plan=canonical(p.model_dump()),
        role_validation=canonical(proof['selected_validation']),binding_prompt=role.render_selected_bindings(original,b,scope,p),
        binding_schema=canonical(role.selected_binding_schema(b,p)),binding_raw=canonical(v.model_dump()),bindings=canonical(v.model_dump()),
        typed_inventory=canonical(typed.model_dump()),inventory=canonical(inventory.model_dump()),
        validation=canonical(proof['legacy_compilation']['typed_projection']['validation']),projection=canonical(proof))
    receipt=dict(schema=role.SELECTION_ATTEMPT,work_id=b.work_id,status='source_role_selections_valid',provider_calls=2,
        terminal=True,source_unchanged=True,scientific_acceptance=False,full_graph_extraction=False,
        model='authored-test-only',item_count=len(inventory.items),
        **{k:dict(path='/authored/'+k,sha256=sha(raw.encode())) for k,raw in captures.items()})
    parent=handoff.build(b,receipt_raw=canonical(receipt),captures=captures)
    return b,parent,receipt,captures,rest


def test_selected_evidence_has_no_retyped_quotes_and_preserves_complete_source():
    original,b,scope,p,v,_=selected_fixture();cat=role.selection_catalog(b)
    jsonschema.validate(p.model_dump(),role.selected_role_schema(b))
    jsonschema.validate(v.model_dump(),role.selected_binding_schema(b,p))
    assert role.inspect_selections(p,b)['valid']
    typed,inventory,proof=role.compile_selections(p,v,b)
    assert [e.value_raw for e in typed.entries[:-1]]==['39 K','37 K','8 nm','8 nm']
    assert typed.entries[-1].type=='unvalued_result' and inventory.items[-1].value_raw is None
    for block in b.blocks:
        assert ''.join(t['quote'] for t in cat['texts'].values() if t['block_id']==block.id)==block.text
    for c in p.model_dump()['claims']:
        assert 'quote' not in canonical(c)
    assert proof['lexical_dispositions_retained'] and not proof['scientific_exclusions_approved']
    assert 'All original' in role.SELECTION_RULES


@pytest.mark.parametrize('role_name,extra',[
    ('numeric_result',{'statement':None}),('numeric_result',{'value_status':'qualitative'}),
    ('unvalued_result',{'numeric_candidate_id':'N1'}),('context',{'numeric_candidate_id':'N1'}),
    ('context',{'statement':None})])
def test_selection_wire_excludes_cross_branch_fields(role_name,extra):
    _,b,_,p,_,_=selected_fixture();raw=p.model_dump()
    row=next(c for c in raw['claims'] if c['role']==role_name);row.update(extra)
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,role.selected_role_schema(b))
    with pytest.raises(ValueError):role.SelectionPlan.model_validate(raw)


@pytest.mark.parametrize('variant',['missing_text','missing_number','false_context','missing_claim_link',
    'bad_number_link','unknown_property','bad_subject','bad_support','duplicate_support','unread','source_hash'])
def test_selection_coverage_and_field_failures_are_visible(variant):
    _,b,_,p,_,_=selected_fixture()
    if variant=='missing_text':p.text_assessments.pop(next(iter(p.text_assessments)))
    elif variant=='missing_number':p.numeric_assessments.pop(next(iter(p.numeric_assessments)))
    elif variant=='false_context':next(a for a in p.text_assessments.values() if a.disposition=='outcomes').disposition='context_only'
    elif variant=='missing_claim_link':next(a for a in p.text_assessments.values() if a.claim_numbers).claim_numbers=[]
    elif variant=='bad_number_link':next(a for a in p.numeric_assessments.values() if a.claim_numbers).claim_numbers=[999]
    elif variant=='unknown_property':p.claims[0].property_evidence.first_text_id='T999'
    elif variant=='bad_subject':p.claims[0].subject_evidence[0].first_text_id='T999'
    elif variant=='bad_support':p.claims[0].support_text_ids=['T999']
    elif variant=='duplicate_support':p.claims[0].support_text_ids*=2
    elif variant=='unread':p.unread_target_units=['T1']
    else:p.catalog_sha256='0'*64
    result=role.inspect_selections(p,b);assert not result['valid']
    with pytest.raises(ValueError,match='selection_plan_not_valid'):role.selected_binding_schema(b,p)


def test_selection_validation_does_not_hide_independent_bad_fields():
    _,b,_,p,_,_=selected_fixture()
    p.claims[0].property_evidence.first_text_id='unknown-property'
    p.claims[0].subject_evidence[0].first_text_id='unknown-subject'
    p.claims[0].support_text_ids=['unknown-support']
    result=role.inspect_selections(p,b)
    paths={r['path'] for r in result['issues']}
    assert {'/claims/0/property_evidence','/claims/0/subject_evidence/0','/claims/0/support_text_ids'}<=paths


@pytest.mark.parametrize('source_kind,accepted',[('original_pdf',True),('original_text',True),('original_tex',False)])
def test_explicit_source_format_controls_percent_comment_rules(source_kind,accepted):
    from ingestion.materials_ner.source_occurrence import positioned_witness
    original,*_=inputs();raw=original.model_dump();text='The shielding is 83% of the reference.\n'
    raw['documents'][0]['source_kind']=source_kind
    raw['blocks'][0].update(text=text,sha256=sha(text.encode()))
    b=role.Bundle.model_validate(raw);start=text.index('83%')
    item=dict(block_id=b.blocks[0].id,start_char=start,end_char=start+3,quote='83%')
    with pytest.raises(ValueError,match='comment_crossing'):positioned_witness(b,item)
    if accepted:assert positioned_witness(b,item,source_format_aware=True)==item
    else:
        with pytest.raises(ValueError,match='comment_crossing'):positioned_witness(b,item,source_format_aware=True)


def test_pdf_text_selection_keeps_percentage_and_trailing_reference_basis():
    original,*_=inputs();raw=original.model_dump();text='The shielding is ∼ 83% of its ambient-pressure value.\n'
    raw['documents'][0]['source_kind']='original_pdf';raw['blocks'][0].update(text=text,sha256=sha(text.encode()))
    original=role.Bundle.model_validate(raw);b,_=role.scope(original,[original.blocks[0].id]);cat=role.selection_catalog(b)
    key=next(k for k,v in cat['texts'].items() if '83%' in v['quote'])
    phrase,location=role.select_text(role.TextSelection(first_text_id=key,last_text_id=None),b,cat)
    assert phrase.quote==text and location['quote']==text
    assert cat['texts'][key]['selectable'] and not cat['texts'][key]['tex_comment_policy']
    display=role._selection_source(b,cat)
    aliases=json.loads(next(line.split(': ',1)[1] for line in display.splitlines() if line.startswith('ORIGINAL BLOCK ALIASES:')))
    rows=json.loads(next(line.split(': ',1)[1] for line in display.splitlines() if line.startswith('ORIGINAL TEXT UNITS [')))
    assert ''.join(row[-1] for row in rows if aliases[row[4]]['block_id']==b.blocks[0].id)==text
    assert '∼ 83%' in display


def test_context_read_does_not_become_a_complete_scientific_exclusion():
    _,b,_,p,v,_=selected_fixture();cat=role.selection_catalog(b)
    key=next(iter(v.coverage_checks))
    v.coverage_checks[key]=role.CoverageCheck(decision='unresolved',reason='A reported result may have been excluded.')
    _,inv,proof=role.compile_selections(p,v,b)
    assert proof['held_outcomes'][-1]['claim_id']=='coverage:'+key
    assert not proof['held_outcomes'][-1]['scientific_exclusion_approved']
    assert any('Unresolved source coverage' in c.description for c in inv.context_assertions)
    parent=dict(run_id='authored',required_occurrences=[],source_role_accounting=dict(held_outcomes=proof['held_outcomes']))
    assert not handoff.outcome_accounting(parent,{})['fully_materialized']


@pytest.mark.parametrize('variant',['missing_coverage','extra_coverage','wrong_parent','wrong_kind','missing_outcome'])
def test_selected_bindings_cannot_drop_or_change_obligations(variant):
    _,b,_,p,v,_=selected_fixture()
    if variant=='missing_coverage':v.coverage_checks.pop(next(iter(v.coverage_checks)))
    elif variant=='extra_coverage':v.coverage_checks['T999']=role.CoverageCheck(decision='unresolved',reason='Authored invalid check.')
    elif variant=='wrong_parent':v.plan_sha256='0'*64
    elif variant=='wrong_kind':v.decisions['A1'].quantity_kind='critical_pressure'
    else:v.decisions.pop('A1')
    with pytest.raises(ValueError):role.compile_selections(p,v,b)


@pytest.mark.parametrize('key',role.SELECTION_CAPTURE_KEYS)
def test_selected_handoff_binds_all_source_captures(key):
    b,_,receipt,captures,_=selected_snapshot();captures[key]+=' '
    with pytest.raises(ValueError,match='source_selection_capture_hash_mismatch'):
        handoff.build(b,receipt_raw=canonical(receipt),captures=captures)


def test_selected_handoff_replays_source_choices_and_real_worker_consumer(tmp_path):
    b,parent,_,_,rest=selected_snapshot();catalog,decisions,links=rest
    assert len(frozen_inventory.verify(parent).items)==5
    store=Store(tmp_path/'worker');job=item_worker.enqueue(store,parent,group_size=2)
    result=run_one(store,job_id=job,provider_override=StageProvider(responses(b,catalog,decisions,links)))
    assert result['state']=='succeeded',result
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['frozen_source_accounting']['materialized_items']==5
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']


def test_selected_invalid_receipt_is_rejected_before_capture_access(tmp_path):
    _,b,*_=selected_fixture();p=tmp_path/'invalid.json'
    p.write_text(canonical(dict(schema=role.SELECTION_ATTEMPT,status='selection_plan_invalid',terminal=True)))
    with pytest.raises(ValueError,match='source_selection_receipt_not_admissible'):frozen_inventory.from_files(b,p,None)
