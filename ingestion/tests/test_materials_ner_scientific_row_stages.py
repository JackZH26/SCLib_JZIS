"""Real-source regressions; authored provider outputs are not a dataset."""
from copy import deepcopy
import json

import jsonschema
import pytest

from ingestion.materials_ner import scientific_row_stages as row, source_atoms as atoms
from ingestion.materials_ner import item_worker, condition_catalog_stages as bridge
from ingestion.materials_ner.contract import digest, canonical
from ingestion.materials_ner.proposals import import_packet,verify_packet,ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_row_catalog_stages import fixture as old_fixture, responses as old_responses
from test_materials_ner_item_stages import StageProvider


def fixture():
    bundle,inventory,parent,context,scope,_,_,raw=old_fixture()
    adapter=row.Adapter(context,scope);palette=adapter.palette(bundle)
    choose=lambda key:dict(candidate_id=key,end_candidate_id=None)
    for sample,cell in zip(raw['samples'],palette['cells'],strict=True):
        cid=cell['id'];local=palette['per_cell'][cid]
        sample['formula']=choose(local['formula'][0]);sample['scope_support']=choose(cid+'/source_row')
        sample['form']=choose(palette['menus']['form'][0])
        sample['variables']=[dict(symbol=choose(local['symbol'][0]),site=None,
            basis=dict(value='unresolved',support=None),amount=dict(candidate_id=local['numbers'][0],missing_status=None),
            applicability=choose(cid+'/row_label'))]
        state=sample['states'][0]
        state['conditions'][0]['basis']=choose(next(k for k in palette['menus']['field']
            if palette['texts'][k]['start_char'] < palette['numbers']['N46']['start_char'] < palette['texts'][k]['end_char']+15))
        if local['fractions'] and sample['isotopes'][0]['fraction']['candidate_id'] is None:
            sample['isotopes'][0]['fraction']['missing_status']='ambiguous'
    raw['protocols'][0]['method']=choose(next(k for k in palette['menus']['method'] if palette['texts'][k]['quote']=='SQUID magnetometer'))
    raw['protocols'][0]['observable']=choose(next(k for k in palette['menus']['observable'] if palette['texts'][k]['quote']=='field-cooled magnetization'))
    raw['limitations']=['Authored real-source test; scientific acceptance and independent reference status remain false.']
    return bundle,inventory,parent,context,scope,adapter,palette,raw


def typed():
    b,i,parent,c,scope,a,p,raw=fixture();choices=atoms.CatalogChoices.model_validate(raw)
    declared=a.check_declarations(choices,i,b,128)
    relations=a.Relations(schema_version='materials-source-catalog-relations/1',work_id=b.work_id,sample_relations=[],
        protocol_uses={'protocol:1':dict(resolution='linked',explanation=None,
            uses=[dict(state_id=s.id,condition_id=v.id,source_span_ids=['S10']) for s in declared.states for v in s.conditions])})
    catalog,proof=a.project(choices,relations,b);assignment=proof['source_atom_projection']['table_assignments']
    mapping=atoms.verify_context(c,b,i)[1]
    owners=a.OwnerBindings(schema_version=a.BINDING_VERSION,work_id=b.work_id,catalog_sha256=digest(catalog.model_dump()),
        decisions={v.id:dict(resolution='bound',**assignment[mapping[v.id]],protocol_id='protocol:1',source_span_ids=v.source_span_ids,
            attribution=dict(source_role='primary',cited_source_raw=None,source_span_ids=v.source_span_ids)) for v in a.requested_items(i.items)})
    return b,i,parent,c,scope,a,p,choices,relations,catalog,owners,proof


def test_caption_coefficient_and_dimensionless_source_provenance():
    b,i,_,_,scope,a,p,choices,relations,catalog,owners,proof=typed()
    jsonschema.validate(choices.model_dump(),a.declaration_schema(b,i))
    assert [s.variables[0].amount.value for s in catalog.samples]==[0,0,0,0,.4]
    assert all(s.variables[0].symbol=='$x$' and s.variables[0].site is None for s in catalog.samples)
    assert all(s.variables[0].amount.unit=='1' and s.composition_basis=='unresolved' for s in catalog.samples)
    assert all(s.formula_raw==r'Y$_{1-x}$Pr$_x$Ba$_2$Cu$_3$O$_{7-\delta}$' for s in catalog.samples)
    assert catalog.samples[1].isotopes[0].fraction.value==80
    assert catalog.samples[1].isotopes[0].fraction.uncertainty.plus==5
    assert catalog.samples[3].isotopes[0].fraction.status=='ambiguous'
    source=proof['source_atom_projection'];entries=[x for x in source['source_fields'] if x.get('unit_convention')]
    assert json.loads(canonical(proof))==proof
    assert len(entries)==5
    for value in entries:
        assert value['source']['source_unit'] is None and value['source']['issues']==['source_unit_not_stated']
        assert value['unit_convention']['canonical_unit']=='1' and not value['unit_convention']['unit_printed']
        assert 'unit' not in value['source']['evidence']
    a.bind(owners,choices,relations,i,b)


@pytest.mark.parametrize('change',['cross_row_formula','wrong_row_number','header_symbol','conjunction_site','nominal',
    'b_field','mu0_h','window_role','false_absence','wrong_isotope_fraction','broad_row_support','physical_bare_number'])
def test_previous_failure_modes_cannot_enter_the_new_catalog(change):
    b,i,_,_,_,a,p,raw=fixture();s=raw['samples'][0]
    choice=lambda k:dict(candidate_id=k,end_candidate_id=None)
    if change=='cross_row_formula':raw['samples'][2]['formula']=choice('A1344')
    elif change=='wrong_row_number':s['variables'][0]['amount']['candidate_id']='N144'
    elif change=='header_symbol':s['variables'][0]['symbol']=choice('A1459')
    elif change=='conjunction_site':s['variables'][0]['site']=choice('A657')
    elif change=='nominal':s['basis']=dict(value='nominal',support=choice('T46'))
    elif change=='b_field':s['states'][0]['conditions'][0]['kind']='magnetic_flux_density'
    elif change=='mu0_h':s['states'][0]['conditions'][0]['kind']='mu0_h'
    elif change=='window_role':s['states'][0]['conditions'][1]['window_position']='interval'
    elif change=='false_absence':raw['samples'][1]['isotopes'][0]['fraction']=dict(candidate_id=None,missing_status='not_reported')
    elif change=='wrong_isotope_fraction':s['isotopes'][0]['fraction']=dict(candidate_id='N42',missing_status=None)
    elif change=='broad_row_support':s['scope_support']=choice('T77')
    else:s['states'][0]['conditions'][1]['quantity']=dict(candidate_id='N74',missing_status=None)
    with pytest.raises(ValueError,match='staged_scientific_row_field_contract_invalid'):
        a.check_declarations(atoms.CatalogChoices.model_validate(raw),i,b,128)


def test_unknown_coefficient_is_not_filled_and_old_conversion_is_unchanged():
    b,i,_,_,_,a,p,raw=fixture();raw['samples'][0]['variables'][0]['amount']=dict(candidate_id=None,missing_status='ambiguous')
    declared,proof=a.compile(atoms.CatalogChoices.model_validate(raw),b)
    assert declared.samples[0].variables[0].amount.status=='ambiguous'
    choices=atoms.CatalogChoices.model_validate(fixture()[-1])
    old=atoms.project(choices,b,a.ownership(b),candidate_catalog=p['catalog'])
    assert all(s['variables'][0]['amount']['status']=='not_extracted' for s in old['graph']['samples'])
    assert not any(x.get('unit_convention') for x in old['source_fields'])


def responses():
    b,i,parent,c,scope,a,p,choices,relations,catalog,owners,proof=typed()
    outputs=old_responses()[-1]
    outputs[:3]=[choices.model_dump(),relations.model_dump(),owners.model_dump()]
    return b,i,parent,c,scope,outputs


def test_full_worker_import_revision_and_unchanged_source(tmp_path):
    b,i,parent,c,scope,outputs=responses();source=digest(b.model_dump())
    store=Store(tmp_path/'row2');provider=StageProvider(outputs)
    job=item_worker.enqueue(store,parent,workflow=row.Adapter.WORKFLOW,field_generation_policy=row.POLICY,
        source_atom_context=c,catalog_scope=scope,max_source_items=128,max_input_tokens=120000,timeout_seconds=600)
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome['state']=='quarantined' and provider.calls==6,outcome
    packet=import_packet(store,job);verify_packet(packet);r=packet['receipt']
    assert not r['staged_errors']
    assert [x['quantity']['value'] for x in r['extraction']['results']]==[91.19,90.99,91.35,91.16,44.63]
    assert [x['variables'][0]['amount']['value'] for x in r['extraction']['samples']]==[0,0,0,0,.4]
    assert r['frozen_source_accounting']['materialized_cells']==5
    assert len(r['staged_assembly']['row_scope']['unrequested_item_ids'])==65
    from ingestion.materials_ner.staged_revision import resolve_parent
    assert resolve_parent(packet)[0].expand(b).model_dump()==r['extraction']
    db=ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert digest(b.model_dump())==source
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
