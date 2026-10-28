"""Target and sensitivity regressions; these synthetic cases are not Gold."""
from copy import deepcopy
import json

import jsonschema
import pytest
from pydantic import ValidationError

from ingestion.materials_ner.contract import parse_extraction
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.proposals import ProposalDatabase, import_packet, verify_packet
from ingestion.materials_ner.sources import make_blocks, save_bundle
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.validation import validate_extraction, training_exclusions
from ingestion.materials_ner.wire_v9 import ScopedExtraction
from ingestion.materials_ner.wire_v10 import DetectionExtraction, output_schema, validate_coverage
from ingestion.materials_ner.worker import configuration, run_one
from test_materials_ner_inventory_v2 import SequenceProvider
from test_materials_ner_pipeline import quantity
from test_materials_ner_scoped_conditions import fixture as scope_fixture


def append_source(bundle, wording):
    bundle.blocks=make_blocks(bundle.documents[0].id,[("synthetic:1",bundle.blocks[0].text+' '+wording)])


def fixture(target='supercurrent'):
    bundle,inventory,raw=scope_fixture();raw['schema_version']='materials-ner-shared/6'
    wording={
        'supercurrent':'Sample A displayed no resolvable supercurrent at the 10 nA current step.',
        'josephson_phase_transition':'Sample A displayed no 0-pi transition in the measured series.',
        'superconductivity':'Sample A displayed no resistive superconducting transition.'}[target]
    append_source(bundle,wording)
    observation=deepcopy(raw['observations'][0]);observation.update(id='N1',inventory_item_ids=['I5'])
    observation['definition'].update(criterion='not_applicable',criterion_raw=None,evidence=[])
    negative={'kind':'non_detection','target':target,'observable':
        {'supercurrent':'supercurrent','josephson_phase_transition':'zero_pi_transition','superconductivity':'resistive_transition'}[target],
        'existence':'not_established','raw':wording,'window_status':'not_reported_in_supplied_source',
        'window_condition_ids':[],'sensitivities':[]}
    if target=='supercurrent':
        negative['sensitivities']=[{'role':'measurement_step','quantity_kind':'electric_current',
            'quantity':quantity(10,'nA','10 nA'),'raw':'10 nA current step'}]
    observation['result'].update(quantity_kind='non_detection',quantity={'status':'not_applicable',
        'raw':None,'relation':None,'value':None,'lower':None,'upper':None,'unit':None,'approximate':False,'uncertainty':None},
        qualifiers=[negative])
    observation['result']['evidence'][0]['fields']=[f for f in observation['result']['evidence'][0]['fields'] if f!='/quantity']+['/qualifiers/0']
    if negative['sensitivities']:observation['result']['evidence'][0]['fields'].append('/qualifiers/0/sensitivities/0')
    raw['observations'].append(observation)
    inventory['items'].append(dict(inventory['items'][0],id='I5',quantity_name_raw=target,value_raw=wording))
    inventory['span_dispositions'][0]['item_ids'].append('I5')
    return bundle,inventory,raw


def report(bundle,raw):
    return validate_extraction(DetectionExtraction.model_validate(raw).expand(bundle),bundle)


def window(bundle,raw,target='superconductivity'):
    append_source(bundle,'No transition was resolved down to 1.8 K.')
    condition={'id':'W','kind':'temperature','role':'detection_window','quantity':quantity(1.8,'K','1.8 K'),
        'orientation_raw':None,'basis_raw':None,'window_position':'lower_limit'}
    raw['states'][0]['conditions'].append(condition)
    raw['states'][0]['evidence'][0]['fields'].append('/conditions/3')
    negative=raw['observations'][-1]['result']['qualifiers'][0]
    negative.update(window_status='reported',window_condition_ids=['W'])
    raw['observations'][-1]['result']['evidence'][0]['fields'].append('/qualifiers/0/window_condition_ids')
    return condition


@pytest.mark.parametrize('target',['superconductivity','supercurrent','josephson_phase_transition'])
def test_target_specific_negative_survives_schema_expansion_and_has_no_tc_label(target):
    bundle,inventory,raw=fixture(target);schema=output_schema(bundle,Inventory.model_validate(inventory))
    jsonschema.Draft202012Validator.check_schema(schema);jsonschema.validate(raw,schema)
    wire=DetectionExtraction.model_validate(raw);extraction=wire.expand(bundle);checked=report(bundle,raw)
    assert checked['valid'],checked['issues']
    assert validate_coverage(wire,Inventory.model_validate(inventory),bundle)['valid']
    assert parse_extraction(extraction.model_dump()).model_dump()==extraction.model_dump()
    assert wire.model_dump()==raw
    negative=extraction.results[-1]
    assert negative.quantity.value is None and negative.quantity.status=='not_applicable'
    gate=training_exclusions(extraction,bundle,checked)['results'][-1]
    assert not gate['eligible'] and 'non_detection_is_not_point_tc' in gate['reason_codes']
    assert ('device_non_detection_is_not_superconductivity_negative_label' in gate['reason_codes'])==(target!='superconductivity')
    if target=='supercurrent':
        normalized=checked['normalized']['/results/4/qualifiers/0/sensitivities/0/quantity']['normalized']
        assert normalized['unit']=='A' and normalized['value']==pytest.approx(1e-8)
        assert negative.qualifiers[0].sensitivities[0].role=='measurement_step'


@pytest.mark.parametrize('mutation',['pair','duplicate','reported_without_ids','unknown_with_ids','numeric','conditional','wrong_kind'])
def test_invalid_negative_shape_is_rejected(mutation):
    bundle,_,raw=fixture();result=raw['observations'][-1]['result'];negative=result['qualifiers'][0]
    if mutation=='pair':negative['observable']='resistive_transition'
    if mutation=='duplicate':result['qualifiers']*=2
    if mutation=='reported_without_ids':negative['window_status']='reported'
    if mutation=='unknown_with_ids':negative['window_condition_ids']=['W']
    if mutation=='numeric':result['quantity']=quantity(0,'K','0 K')
    if mutation=='conditional':result['qualifiers'].append({'kind':'conditional_existence','condition':'if_superconducting','raw':'if superconducting','tc_bound':None})
    if mutation=='wrong_kind':result['quantity_kind']='tc'
    with pytest.raises(ValidationError):DetectionExtraction.model_validate(raw).expand(bundle)


@pytest.mark.parametrize('mutation,code',[
    ('device_as_sc','device_non_detection_misclassified_as_superconductivity'),
    ('threshold','measurement_step_is_not_detection_threshold'),
    ('missing_evidence','field_evidence_missing'),
    ('invented_raw','sensitivity_raw_not_in_field_evidence'),
    ('unreported','reported_sensitivity_quantity_required'),
    ('computed','non_detection_requires_observed_measurement'),
    ('method','non_detection_method_unresolved'),
    ('wrong_window','non_detection_window_owner_mismatch'),
    ('geometry','non_detection_window_role_or_quantity_mismatch'),
    ('fit_window','non_detection_window_role_or_quantity_mismatch'),
])
def test_scientific_conflicts_are_quarantined_without_reinterpreting_source(mutation,code):
    bundle,_,raw=fixture();result=raw['observations'][-1]['result'];negative=result['qualifiers'][0]
    if mutation=='device_as_sc':negative.update(target='superconductivity',observable='unspecified')
    if mutation=='threshold':negative['sensitivities'][0]['role']='detection_threshold'
    if mutation=='missing_evidence':result['evidence'][0]['fields'].remove('/qualifiers/0/sensitivities/0')
    if mutation=='invented_raw':negative['sensitivities'][0]['raw']='invented sensitivity'
    if mutation=='unreported':negative['sensitivities'][0]['quantity']={'status':'not_reported'}
    if mutation=='computed':result['origin']='computed'
    if mutation=='method':raw['protocols'][0]['method']=None
    if mutation in {'wrong_window','geometry','fit_window'}:
        negative.update(window_status='reported',window_condition_ids=[{'wrong_window':'foreign-W','geometry':'geometry','fit_window':'fit_window'}[mutation]])
        result['evidence'][0]['fields'].append('/qualifiers/0/window_condition_ids')
    checked=report(bundle,raw)
    assert code in {i['code'] for i in checked['issues']}
    assert not checked['scientific_acceptance'] and not checked['ml_training_eligible']


@pytest.mark.parametrize('target',['superconductivity','supercurrent','josephson_phase_transition'])
def test_explicit_same_state_window_is_retained_without_becoming_tc(target):
    bundle,_,raw=fixture(target);window(bundle,raw)
    assert report(bundle,raw)['valid']
    raw['states'][0]['conditions'].reverse()
    # Bind the evidence after reordering; the selected condition ID stays W.
    fields=raw['states'][0]['evidence'][0]['fields']
    raw['states'][0]['evidence'][0]['fields']=[f for f in fields if not f.startswith('/conditions/')]+[f'/conditions/{i}' for i in range(4)]
    assert report(bundle,raw)['valid']
    assert raw['observations'][-1]['result']['quantity']['value'] is None


def test_conditional_tc_bound_does_not_supply_its_own_measurement_floor():
    bundle,_,raw=fixture('superconductivity');window(bundle,raw)
    wording='If superconducting at all, the critical temperature is lower than 1.8 K.'
    append_source(bundle,wording)
    raw['observations'][-1]['result']['qualifiers'].append({'kind':'conditional_existence',
        'condition':'if_superconducting','raw':wording,'tc_bound':{
            **quantity(None,'K','lower than 1.8 K'),'relation':'lt','upper':1.8}})
    raw['observations'][-1]['result']['evidence'][0]['fields']+=['/qualifiers/1','/qualifiers/1/tc_bound']
    assert 'conditional_bound_window_requires_source_review' in {i['code'] for i in report(bundle,raw)['issues']}


@pytest.mark.parametrize('role',['detection_window','study_extent'])
@pytest.mark.parametrize('kind,unit',[('temperature','K'),('thickness','nm')])
def test_an_exact_setting_without_endpoint_semantics_cannot_be_a_scan_window(role,kind,unit):
    bundle,_,raw=fixture();c=window(bundle,raw)
    c.update(kind=kind,role=role,window_position='unspecified' if role=='detection_window' else None)
    c['quantity']=quantity(4.5,unit,f'4.5 {unit}');append_source(bundle,f'The measurement was at 4.5 {unit}.')
    assert 'non_detection_point_is_not_scan_window' in {i['code'] for i in report(bundle,raw)['issues']}


def test_historical_schema_refuses_new_fields_and_target_instead_of_reinterpreting():
    bundle,_,raw=fixture();old=deepcopy(raw);old['schema_version']='materials-ner-shared/5'
    with pytest.raises(ValidationError):ScopedExtraction.model_validate(old)


def test_a_specimen_point_cannot_be_turned_into_an_inequality_to_imply_a_scan():
    bundle, _, raw = fixture()
    condition = window(bundle, raw)
    append_source(bundle, 'No supercurrent is resolvable at 4.5 nm.')
    condition.update(kind='thickness', role='sample_geometry', window_position=None)
    condition['quantity'] = dict(quantity(None, 'nm', '4.5'), relation='gt', lower=4.5)
    before = deepcopy(raw)
    issues = {item['code'] for item in report(bundle, raw)['issues']}
    assert 'numeric_value_disagrees_with_raw' in issues
    assert 'non_detection_window_role_or_quantity_mismatch' in issues
    assert raw == before


def test_worker_packet_reconstructs_and_imports_exact_target_and_sensitivity(tmp_path):
    bundle,inventory,raw=fixture();store=Store(tmp_path)
    bundle_hash,_=save_bundle(tmp_path,bundle);config=configuration(workflow='inventory_v10')
    assert config['max_evidence_patches']==config['max_extraction_repairs']==0
    job=store.enqueue(work_id=bundle.work_id,bundle_hash=bundle_hash,config=config)
    outcome=run_one(store,job_id=job,provider_override=SequenceProvider([inventory,raw]))
    assert outcome['state']=='succeeded',outcome
    packet=import_packet(store,job);verify_packet(packet)
    assert packet['receipt']['extraction']['schema_version']=='materials-ner/8'
    database=ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    with database.connect() as connection:
        stored=json.loads(connection.execute('SELECT payload FROM runs').fetchone()[0])
        assert stored==packet
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
