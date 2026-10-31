"""Source-backed failure-mode tests; these synthetic cases are not scientific Gold."""
from copy import deepcopy
import json
import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner import source_choice_graph as flow
from ingestion.materials_ner.contract import canonical, digest, parse_extraction, Quantity
from ingestion.materials_ner.contract_v9 import ExtractionV9
from ingestion.materials_ner.contract_v10 import ConditionV10
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.numeric_occurrences import source_candidates
from ingestion.materials_ner.quantities import normalize
from ingestion.materials_ner.sources import parse_local
from ingestion.materials_ner.sources import sha
from ingestion.materials_ner.proposals import review_rows, verify_packet, ProposalDatabase
from ingestion.materials_ner.field_candidates import text_candidates


def fixture(tmp_path):
    text = r'Our FeSe crystal has $T_c$ = 20 K and 12 K for $H$ = 9 T and 26.42 T, respectively, with $H$ $\perp$ $c$.'
    p = tmp_path/'paper.tex'; p.write_bytes(text.encode())
    bundle = parse_local(p, work_id='arxiv:test', title='Test', source_uri='test:paper.tex',
        publication_version='v1', processing_permission='allowed')
    block = bundle.blocks[0]
    sample = dict(id='S1', label=None, formula_raw='FeSe', composition_basis='unresolved',
        identity_resolution='source_scoped', target_kind='bulk', form_raw=None, substrate_raw=None,
        isotopes=[], variables=[], evidence=[dict(block_id=block.id, quote=text, field=f)
            for f in ['/formula_raw', '/identity_resolution', '/target_kind']])
    base = ExtractionV9.model_validate(dict(schema_version='materials-ner/9', work_id=bundle.work_id,
        outcome='incomplete', empty_reason=None, processed_block_ids=[block.id], unread_block_ids=[],
        limitations=['Synthetic engineering fixture.'], samples=[sample], states=[], protocols=[], results=[]))
    records = []
    for i, raw in enumerate(['20 K', '12 K'], 1):
        candidate = next(v for v in source_candidates(text) if v['quote'] == raw)
        records.append(dict(assertion_id='A'+str(i), existing_sample_id='S1',
            source_span_ids=list(source_catalog(bundle)['spans']), compiled_quantity=candidate['quantity'],
            quantity_evidence=[dict(v, block_id=block.id, field='/quantity/'+k) for k, v in candidate['evidence'].items()]))
    request = dict(work_id=bundle.work_id, bundle_sha256=digest(bundle.model_dump()),
                   base_graph_sha256=digest(base.model_dump()), records=records)
    return bundle, base, request


def selection(bundle, base, request):
    catalog = flow.candidates(bundle, base, request); assertions = {}
    for row, field in zip(request['records'], ['9 T', '26.42 T']):
        aid = row['assertion_id']; c = catalog[aid]
        text = lambda raw: next(k for k, v in c['texts'].items() if v['quote'] == raw)
        number = next(k for k, v in c['numbers'].items() if v['quote'] == field)
        evidence = lambda fields: [dict(span_ids=['C1'], fields=fields)]
        assertions[aid] = dict(outcome='append', name_candidate_id=text('$T_c$'),
            sample_link_reason='The source names this crystal.',
            state=dict(label=None, preparation_raw=None, conditions=[dict(id='measurement_field',
                kind='reported_magnetic_field', role='measurement', quantity_occurrence_id=number,
                orientation_candidate_id=text(r'$H$ $\perp$ $c$'), basis_candidate_id=text('$H$'), window_position=None)],
                evidence=evidence(['/sample_id', '/conditions/0/kind', '/conditions/0/role'])),
            procedure=dict(method=None, method_class='unspecified', observable=None, details_raw=None,
                           parameters=[], context_uses=[], evidence=[]),
            result=dict(quantity_kind='tc', origin='observed', source_role='primary', component_candidate_id=None,
                interpretation_candidate_id=None, cited_source_candidate_id=None, dependencies=[], qualifiers=[],
                definition=dict(criterion='unspecified', criterion_raw=None, parameters=[]),
                evidence=evidence(['/sample_id', '/state_id', '/protocol_id', '/quantity_kind', '/origin', '/source_role'])))
    return dict(schema_version=flow.POLICY, work_id=bundle.work_id, assertions=assertions, limitations=[])


def test_exact_choices_retain_tc_conditions_and_original_graph(tmp_path):
    b, base, request = fixture(tmp_path); before = base.model_dump(); output = selection(b, base, request)
    schema = flow.output_schema(b, base, request); jsonschema.Draft202012Validator.check_schema(schema)
    projection, report = flow.project(flow.parse(canonical(output), b, base, request), b, base, request)
    assert base.model_dump() == before and projection['existing_entities_unchanged']
    graph = parse_extraction(projection['graph']); assert graph.schema_version == 'materials-ner/10'
    assert [r.quantity.value for r in graph.results] == [20, 12]
    assert [s.conditions[0].quantity.value for s in graph.states] == [9, 26.42]
    assert all(s.conditions[0].orientation_raw == r'$H$ $\perp$ $c$' for s in graph.states)
    assert all(s.conditions[0].basis_raw == '$H$' for s in graph.states)
    assert all(r.quantity_name_raw == '$T_c$' and r.definition.criterion == 'unspecified' for r in graph.results)
    assert all(p.method is None for p in graph.protocols)
    assert not [i for i in report['native']['issues'] if i['path'].startswith(('/states/', '/results/', '/protocols/'))]
    for r in report['task_features']['results']:
        for task in r['tasks'].values():
            assert not task['eligible_for_training'] and not task['condition_candidates']
    assert not report['scientific_acceptance'] and report['qualified_ml_rows'] == 0


@pytest.mark.parametrize('mutation', ['invented_name', 'id_pointer', 'wrong_entity_pointer', 'tesla_as_H', 'null_basis'])
def test_generation_rejects_known_mapping_failures(tmp_path, mutation):
    b, base, request = fixture(tmp_path); output = selection(b, base, request); a = output['assertions']['A1']
    if mutation == 'invented_name': a['name_candidate_id'] = 'transition temperature'
    if mutation == 'id_pointer': a['state']['evidence'][0]['fields'] = ['/conditions/measurement_field/role']
    if mutation == 'wrong_entity_pointer': a['procedure']['evidence'] = [dict(span_ids=['C1'], fields=['/sample_id'])]
    if mutation == 'tesla_as_H': a['state']['conditions'][0]['kind'] = 'magnetic_field_strength'
    if mutation == 'null_basis': a['state']['conditions'][0]['basis_candidate_id'] = None
    with pytest.raises((jsonschema.ValidationError, ValidationError)):
        flow.parse(canonical(output), b, base, request)


@pytest.mark.parametrize('mutation', ['base', 'bundle', 'source_scope', 'number'])
def test_request_cannot_rebind_frozen_source_quantity(tmp_path, mutation):
    b, base, request = fixture(tmp_path)
    if mutation == 'base': request['base_graph_sha256'] = '0'*64
    if mutation == 'bundle': request['bundle_sha256'] = '0'*64
    if mutation == 'source_scope': request['records'][0]['source_span_ids'] = ['S999']
    if mutation == 'number': request['records'][0]['compiled_quantity']['value'] = 21
    with pytest.raises(ValueError): flow.candidates(b, base, request)


def test_all_held_does_not_modify_entities(tmp_path):
    b, base, request = fixture(tmp_path)
    output = dict(schema_version=flow.POLICY, work_id=b.work_id, assertions={r['assertion_id']:
        dict(outcome='held', reason='Unresolved ownership.') for r in request['records']}, limitations=[])
    p, v = flow.project(flow.parse(canonical(output), b, base, request), b, base, request)
    assert p['graph'] == dict(base.model_dump(), schema_version='materials-ner/10')
    assert v['appended_results'] == 0 and v['held_targets'] == 2


def test_unknown_field_convention_is_never_converted(tmp_path):
    b, base, request = fixture(tmp_path)
    q = deepcopy(request['records'][0]['compiled_quantity']); q.update(unit='T', raw='20 T')
    value = Quantity.model_validate(q)
    assert normalize('reported_magnetic_field', value)['normalized'] is None
    with pytest.raises(ValueError, match='unregistered_unit'): normalize('magnetic_field_strength', value)
    q.update(unit='K', raw='20 K')
    with pytest.raises(ValueError, match='unregistered_reported_magnetic_field_unit'):
        normalize('reported_magnetic_field', Quantity.model_validate(q))
    condition = dict(id='field', kind='reported_magnetic_field', role='measurement', quantity=q,
                     orientation_raw=None, basis_raw=None, window_position=None)
    with pytest.raises(ValidationError, match='requires_source_basis'): ConditionV10.model_validate(condition)


def packet_fixture(tmp_path):
    b, base, request = fixture(tmp_path); raw = canonical(selection(b, base, request))
    projection, report = flow.project(flow.parse(raw, b, base, request), b, base, request)
    receipt = dict(work_id=b.work_id, bundle_sha256=digest(b.model_dump()), state='quarantined',
        raw_output_sha256=sha(raw.encode()), extraction=projection['graph'], validation=report['native'],
        source_choice_base_graph=base.model_dump(), source_choice_request=request,
        source_choice_audit={k:v for k,v in projection.items() if k != 'graph'}, scientific_acceptance=False,
        config=dict(output_format=flow.POLICY, model='synthetic-test', request_sha256=digest(request),
            schema_sha256=digest(flow.output_schema(b, base, request)), prompt_sha256=sha(flow.render(b, base, request).encode())))
    packet = dict(schema='materials-ner-proposals/2', job_id='synthetic', run_id=digest(receipt),
        work_id=b.work_id, bundle_hash=digest(b.model_dump()), bundle=b.model_dump(), receipt=receipt,
        raw_output=raw, rows=review_rows(parse_extraction(projection['graph']), report['native']),
        evidence=report['native']['resolved_evidence'], scientific_acceptance=False, ml_training_eligible=False)
    packet['packet_hash']=digest(packet)
    return packet


def test_proposal_replay_and_idempotent_storage_preserve_unresolved_convention(tmp_path):
    packet=packet_fixture(tmp_path); verify_packet(packet)
    db=ProposalDatabase(tmp_path/'proposals')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    with db.connect() as connection:
        conditions=[json.loads(r['payload']) for r in connection.execute('SELECT payload FROM conditions')]
        assert len(conditions)==2 and all(c['kind']=='reported_magnetic_field' for c in conditions)
        assert [c['quantity']['value'] for c in conditions]==[9,26.42]


def test_rehashed_packet_cannot_change_result_behind_original_selections(tmp_path):
    packet=packet_fixture(tmp_path)
    packet['receipt']['extraction']['results'][0]['quantity']['value']=21
    packet['run_id']=digest(packet['receipt'])
    packet['packet_hash']=digest({k:v for k,v in packet.items() if k!='packet_hash'})
    with pytest.raises(ValueError,match='source_choice_receipt_graph_mismatch'): verify_packet(packet)


def test_tex_linebreak_does_not_hide_later_original_tc_symbol():
    text=r'Prior $A$\\$B$.'+'\r\n\r\n'+r'Current $T_{c}$ = 20 K.'
    legacy=text_candidates(text,0,len(text))
    corrected=text_candidates(text,0,len(text),dollar_escape_parity=True)
    assert '$T_{c}$' not in [x['quote'] for x in legacy if x['kind']=='math']
    assert [x['quote'] for x in corrected if x['kind']=='math']==['$A$','$B$','$T_{c}$']
    assert all(text[x['start_char']:x['end_char']]==x['quote'] for x in corrected)


def test_escaped_dollars_and_commented_math_do_not_create_false_candidates():
    text=r'Price \$5. $broken % commented $ token'+'\n'+r'continued$ and $T_c$ = 20 K.'
    values=text_candidates(text,0,len(text),dollar_escape_parity=True)
    assert [x['quote'] for x in values if x['kind']=='math']==['$T_c$']


def test_prompt_scope_uses_visible_source_aliases_without_changing_ledger(tmp_path):
    b, base, request=fixture(tmp_path);original=deepcopy(request)
    request['prompt_scope_policy']='active_aliases_v1'
    rendered=flow.render(b,base,request)
    line=next(s for s in rendered.splitlines() if s.startswith('REQUESTED ASSERTIONS: '))
    model_request=json.loads(line.removeprefix('REQUESTED ASSERTIONS: '))
    assert all(r['source_span_ids']==['C1'] for r in model_request)
    assert request['records']==original['records']
    assert all(r['source_span_ids']==['S1'] for r in request['records'])


def test_shared_catalogs_preserve_scope_and_make_condition_ids_explicit(tmp_path):
    b, base, request=fixture(tmp_path)
    request.update(generation_policy='shared_source_choices_v1',prompt_scope_policy='active_aliases_v1')
    raw=selection(b,base,request);schema=flow.output_schema(b,base,request)
    assertions=schema['$defs']['SourceChoiceAssertions']['properties']
    assert assertions['A1']['anyOf']==assertions['A2']['anyOf']
    text=flow.render(b,base,request)
    c=json.loads(next(s for s in text.splitlines() if s.startswith('EXACT SOURCE CHOICES: ')).removeprefix('EXACT SOURCE CHOICES: '))
    assert c['assertion_catalogs']=={'A1':'L1','A2':'L1'} and len(c['catalogs'])==1
    catalog=c['catalogs']['L1'];ids=catalog['condition_quantity_occurrence_ids_by_kind']['reported_magnetic_field']
    assert {catalog['numeric_occurrences'][i]['quote'] for i in ids}=={'9 T','26.42 T'}
    assert 'magnetic_field_strength' not in catalog['condition_quantity_occurrence_ids_by_kind']
    p,v=flow.project(flow.parse(canonical(raw),b,base,request),b,base,request)
    assert v['appended_results']==2 and [r['quantity']['value'] for r in p['graph']['results']]==[20,12]
