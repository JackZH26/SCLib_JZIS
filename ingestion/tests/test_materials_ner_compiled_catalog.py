"""Real-source compiler checks; authored selections are regression inputs only."""
from copy import deepcopy

import jsonschema
import pytest

from materials_private_fixtures import private_json

from ingestion.materials_ner import compiled_catalog as module
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.inventory import Inventory
from ingestion.materials_ner.sources import Bundle, sha
from ingestion.materials_ner.field_quantity import field_quantity_issues
from ingestion.materials_ner.contract import Evidence, Quantity


def source():
    value = private_json('materials_ner_compiled_catalog_source.json')
    return Bundle.model_validate(value['bundle']), Inventory.model_validate(value['inventory'])


def choice(catalog, literal, context=None):
    options = [(key, v) for key,v in catalog['texts'].items()
               if literal in v['quote'] and (context is None or context in v['quote'])]
    key, value = min(options, key=lambda pair:len(pair[1]['quote']))
    return dict(candidate_id=key, literal=literal)


def number(catalog, raw):
    options = [(key,v) for key,v in catalog['numbers'].items() if v['quote']==raw]
    assert len(options)==1, raw
    return dict(candidate_id=options[0][0], missing_status=None)


def selected():
    bundle, inventory = source()
    catalog = module.candidates(bundle)
    c = lambda literal, context=None: choice(catalog,literal,context)
    basis = dict(value='unresolved',support=None)
    general = c('Polycrystalline')
    source_formula = r'Y$_{1-x}$Pr$_x$Ba$_2$Cu$_3$O$_{7-\delta}$'
    series=[]
    for isotope in (16,18):
        label = c('not substituted ($^{16}$O)') if isotope==16 else c('$^{18}$O\nsubstituted samples')
        abundance = dict(candidate_id=None,missing_status='not_reported') if isotope==16 else number(catalog,r'80(5)\%')
        conditions=[dict(kind='reported_magnetic_field',role='measurement',
            quantity=number(catalog,'1.0~mT'),basis=c('field of 1.0~mT'),orientation=None,
            window_position=None,applicability=c('field of 1.0~mT')),
            dict(kind='temperature',role='study_extent',
                quantity=number(catalog,r'between $1.75$~K and $100$~K'),basis=None,orientation=None,
                window_position=None,applicability=c(r'between $1.75$~K and $100$~K'))]
        series.append(dict(label=label,formula=c(source_formula,'Polycrystalline'),formula_missing_reason=None,
            basis=basis,identity_resolution='source_scoped',target_kind='unresolved',scope_support=general,
            form=general,substrate=None,isotopes=[dict(isotope_label=label,fraction=abundance,applicability=label)],
            variables=[],alternative_formulas=[],states=[dict(label=None,preparation=None,sample_support=label,conditions=conditions)]))
    data=dict(schema_version=module.POLICY,work_id=bundle.work_id,samples=series,
        protocols=[dict(method=c('SQUID magnetometer'),method_class='magnetization',observable=c('field-cooled magnetization'),
            details=c(r'between $1.75$~K and $100$~K'),applicability=c('field-cooled magnetization'),parameters=[]),
            dict(method=c(r'zero-field $\mu$SR'),method_class='muon_spin',observable=None,details=None,
                applicability=c(r'zero-field $\mu$SR'),parameters=[])],
        processed_block_ids=['B1'],unread_block_ids=[],unrepresented=[],
        limitations=['Regression-authored focused catalog, not an independent reference or complete-paper extraction.'])
    return bundle, inventory, catalog, data


def test_real_source_isotope_form_and_field_compile_without_generated_values_or_paths():
    bundle, inventory, catalog, data=selected()
    before=deepcopy(bundle.model_dump())
    jsonschema.validate(data,module.output_schema(bundle))
    result=module.project(module.parse(canonical(data)),bundle)
    graph=result['graph'];a,b=graph['samples']
    assert a['isotopes'][0]['fraction']['status']=='not_reported'
    q=b['isotopes'][0]['fraction']
    assert (q['value'],q['unit'],q['uncertainty']['minus'])==(80.0,'%',5.0)
    assert q['raw']==r'80(5)\%'
    assert a['form_raw']==b['form_raw']=='Polycrystalline'
    assert a['composition_basis']==b['composition_basis']=='unresolved'
    assert graph['states'][0]['conditions'][0]['kind']=='reported_magnetic_field'
    span=graph['states'][0]['conditions'][1]
    assert span['quantity']['relation']=='interval' and span['quantity']['lower']==1.75 and span['quantity']['upper']==100
    assert span['window_position'] is None and span['role']=='study_extent'
    assert graph['protocols'][1]['method']==r'zero-field $\mu$SR'
    assert all(c['quantity']['value']!=0 for s in graph['states'] for c in s['conditions'])
    for s in graph['states']:
        for i,c in enumerate(s['conditions']):
            assert field_quantity_issues(Quantity.model_validate(c['quantity']),
                [Evidence.model_validate(e) for e in s['evidence']],f'/conditions/{i}/quantity')==[]
    assert graph['outcome']=='incomplete' and not graph['results']
    assert not result['scientific_acceptance'] and not result['ml_training_eligible']
    assert bundle.model_dump()==before and len(inventory.items)==70
    assert not any('evidence_field_not_present'==issue['code'] for issue in result['validation']['issues'])
    for item in result['source_fields']:
        s=item['source'];block=next(b for b in bundle.blocks if b.id==s['block_id'])
        assert block.text[s['start_char']:s['end_char']]==s['quote']
        assert item['field'].startswith(('/samples/','/states/','/protocols/'))


@pytest.mark.parametrize('mutation',[
    'generated_value','generated_pointer','wrong_fraction_unit','foreign_number','foreign_text',
    'absent_literal','ambiguous_literal','nominal_without_source','nominal_with_unrelated_source',
    'missing_number_status','duplicate_block','unknown_block','uncovered_block',
    'measurement_window_marker','field_basis_missing','method_missingness','mixed_isotope_label',
    'formula_missingness','wrong_work'])
def test_unsupported_source_generation_or_invalid_ownership_is_rejected(mutation):
    bundle,_,catalog,data=selected();sample=data['samples'][0]
    if mutation=='generated_value':sample['isotopes'][0]['fraction']['value']=1
    elif mutation=='generated_pointer':sample['evidence']=[dict(field='/parameters/0')]
    elif mutation=='wrong_fraction_unit':sample['isotopes'][0]['fraction']=number(catalog,'1.0~mT')
    elif mutation=='foreign_number':sample['isotopes'][0]['fraction']=dict(candidate_id='N99999',missing_status=None)
    elif mutation=='foreign_text':sample['form']['candidate_id']='T99999'
    elif mutation=='absent_literal':sample['form']['literal']='a fabricated single crystal'
    elif mutation=='ambiguous_literal':sample['isotopes'][0]['isotope_label']['literal']='$^{16}$O'
    elif mutation=='nominal_without_source':sample['basis']=dict(value='nominal',support=None)
    elif mutation=='nominal_with_unrelated_source':sample['basis']=dict(value='nominal',support=choice(catalog,'Polycrystalline'))
    elif mutation=='missing_number_status':sample['isotopes'][0]['fraction']['missing_status']=None
    elif mutation=='duplicate_block':data['processed_block_ids']=['B1','B1']
    elif mutation=='unknown_block':data['processed_block_ids']=['B999']
    elif mutation=='uncovered_block':data['processed_block_ids']=[]
    elif mutation=='measurement_window_marker':sample['states'][0]['conditions'][0]['window_position']='interval'
    elif mutation=='field_basis_missing':sample['states'][0]['conditions'][0]['basis']=None
    elif mutation=='method_missingness':data['protocols'][0]['method']=None
    elif mutation=='mixed_isotope_label':sample['isotopes'][0]['isotope_label']=choice(catalog,'substituted ($^{18}$O) and not substituted ($^{16}$O)')
    elif mutation=='formula_missingness':sample['formula']=None
    else:data['work_id']='arxiv:wrong'
    with pytest.raises(ValueError):module.project(module.parse(canonical(data)),bundle)


def test_a_symbol_without_a_reported_abundance_remains_unresolved_not_a_hundred_percent():
    bundle,_,catalog,data=selected()
    candidate=next(k for k,v in catalog['numbers'].items() if v['quote']=='16' and v['quantity'] is None)
    data['samples'][0]['isotopes'][0]['fraction']=dict(candidate_id=candidate,missing_status=None)
    result=module.project(module.parse(canonical(data)),bundle)
    quantity=result['graph']['samples'][0]['isotopes'][0]['fraction']
    assert quantity['status']=='not_extracted' and quantity['value'] is None
    assert any(x['path']=='/samples/0/isotopes/0/fraction' for x in result['unresolved_fields'])


def receipt(bundle,inventory,data):
    raw=canonical(data)
    return dict(schema=module.POLICY,terminal=True,scientific_acceptance=False,ml_training_eligible=False,
        bundle_sha256=digest(bundle.model_dump()),inventory_sha256=digest(inventory.model_dump()),
        prompt_sha256=sha(module.render(bundle,inventory).encode()),schema_sha256=digest(module.output_schema(bundle)),
        raw_output_sha256=sha(raw.encode()),projection=module.project(module.parse(raw),bundle)),raw


@pytest.mark.parametrize('mutation',[None,'source','inventory','raw','graph','approval','training','terminal'])
def test_receipt_replay_cannot_relabel_source_science_or_generated_graph(mutation):
    bundle,inventory,_,data=selected();r,raw=receipt(bundle,inventory,data)
    if mutation=='source':bundle.blocks[0].text+=' Invented.'
    elif mutation=='inventory':inventory.items[0].value_raw='999 K'
    elif mutation=='raw':raw+=' '
    elif mutation=='graph':r['projection']['graph']['samples'][0]['isotopes'][0]['fraction']['value']=1
    elif mutation=='approval':r['scientific_acceptance']=True
    elif mutation=='training':r['ml_training_eligible']=True
    elif mutation=='terminal':r['terminal']=False
    if mutation:
        with pytest.raises(ValueError):module.verify_receipt(r,bundle,inventory,raw)
    else:assert module.verify_receipt(r,bundle,inventory,raw)==r['projection']


def test_duplicate_json_keys_are_not_silently_overwritten():
    with pytest.raises(ValueError,match='duplicate_json_key'):
        module.parse('{"work_id":"a","work_id":"b"}')
