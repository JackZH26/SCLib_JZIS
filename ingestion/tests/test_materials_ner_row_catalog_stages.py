"""Scoped real-source results without shrinking the retained paper denominator.

Authored provider fixtures below are regression evidence only, not Gold or new
Luna data. Field menus and source joins remain scientific review proposals.
"""
from copy import deepcopy
import json
import re

import jsonschema
import pytest

from ingestion.materials_ner import row_catalog_stages as row, source_atoms as atoms
from ingestion.materials_ner import item_stages, item_worker
from ingestion.materials_ner.contract import canonical, digest, Quantity
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.numeric_occurrences import source_candidates
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_source_atom_stages import source
from test_materials_ner_item_stages import StageProvider

CELLS = ['T1:R1:C2','T1:R1:C3','T1:R13:C2','T1:R13:C3','T1:R14:C2']


def fixture():
    bundle, inventory, parent, context, _, _ = source()
    scope = row.scope(bundle, inventory, context, cell_ids=CELLS, support_span_ids=[f'S{i}' for i in range(7,16)])
    adapter = row.Adapter(context, scope); palette = adapter.palette(bundle)
    def literal(raw, *, clause=None, kind=None):
        selected = next(key for key,value in palette['texts'].items() if value['quote'] == raw
            and (clause is None or value['clause_id'] == clause) and (kind is None or value['kind'] == kind)
            and key.startswith('A'))
        return dict(candidate_id=selected,end_candidate_id=None)
    support = lambda key: dict(candidate_id=key,end_candidate_id=None)
    def number(raw, *, start=None):
        key = next(key for key,value in palette['numbers'].items() if value['quote'] == raw and (start is None or value['start_char']==start))
        return dict(candidate_id=key,missing_status=None)
    basis = dict(value='unresolved',support=None)
    samples = []
    for cell in palette['cells']:
        isotope = 18 if cell['column'] == 3 else 16
        isotope_label = literal('$^{'+str(isotope)+'}$O',kind='isotope_literal')
        abundance = (number(r'80(5)\%') if isotope == 18 and not cell['footnotes']
                     else dict(candidate_id=None,missing_status='not_reported'))
        conditions = [dict(kind='reported_magnetic_field',role='measurement',quantity=number('1.0~mT'),
            basis=literal('field',clause='T54'),orientation=None,window_position=None,applicability=support('T54')),
            dict(kind='temperature',role='study_extent',quantity=number(r'between $1.75$~K and $100$~K'),
                basis=None,orientation=None,window_position=None,applicability=support('T54'))]
        samples.append(dict(label=isotope_label, formula=literal(r'Y$_{1-x}$Pr$_x$Ba$_2$Cu$_3$O$_{7-\delta}$',clause='T46'),
            formula_missing_reason=None, basis=basis, identity_resolution='source_scoped',target_kind='bulk',
            scope_support=support('T46'),form=literal('Polycrystalline',clause='T46'),substrate=None,
            isotopes=[dict(isotope_label=isotope_label,fraction=abundance,applicability=support(cell['id']+'/source_header'))],
            variables=[],alternative_formulas=[],states=[dict(label=None,
                preparation=support(cell['id']+'/note_'+cell['footnotes'][0]['label']) if cell['footnotes'] else None,
                sample_support=support(cell['id']+'/source_row'),conditions=conditions,table_cell_ids=[cell['id']])]))
    method = literal('SQUID',clause='T53'); method['end_candidate_id'] = literal('magnetometer',clause='T53')['candidate_id']
    observable = literal('field-cooled',clause='T53'); observable['end_candidate_id'] = literal('magnetization',clause='T53')['candidate_id']
    raw = dict(schema_version=atoms.POLICY,work_id=bundle.work_id,samples=samples,
        protocols=[dict(method=method,method_class='magnetization',observable=observable,details=support('T55'),
            applicability=support('T53'),parameters=[])],processed_block_ids=['B1'],unread_block_ids=[],unrepresented=[],
        limitations=['Authored scoped regression; composition amounts and scientific specimen continuity remain unreviewed.'])
    return bundle, inventory, parent, context, scope, adapter, palette, raw


def typed():
    bundle, inventory, parent, context, scope, adapter, palette, raw = fixture()
    choices = atoms.CatalogChoices.model_validate(raw)
    declared = adapter.check_declarations(choices, inventory, bundle, 128)
    relation = adapter.Relations(schema_version='materials-source-catalog-relations/1',work_id=bundle.work_id,
        sample_relations=[], protocol_uses={'protocol:1':dict(resolution='linked',explanation=None,
            uses=[dict(state_id=state.id,condition_id=condition.id,source_span_ids=['S10'])
                  for state in declared.states for condition in state.conditions])})
    catalog, proof = adapter.project(choices,relation,bundle)
    mapping = atoms.verify_context(context,bundle,inventory)[1]
    assignment = proof['source_atom_projection']['table_assignments']
    decisions = {}
    for item in adapter.requested_items(inventory.items):
        decisions[item.id] = dict(resolution='bound',**assignment[mapping[item.id]],protocol_id='protocol:1',
            source_span_ids=item.source_span_ids,attribution=dict(source_role='primary',cited_source_raw=None,source_span_ids=item.source_span_ids))
    selection = adapter.OwnerBindings(schema_version=adapter.BINDING_VERSION,work_id=bundle.work_id,
        catalog_sha256=digest(catalog.model_dump()),decisions=decisions)
    return bundle,inventory,parent,context,scope,adapter,palette,choices,relation,catalog,selection


def test_exact_field_menus_scope_and_table_treatments():
    bundle,inventory,_,_,scope,adapter,palette,choices,relation,catalog,selection = typed()
    jsonschema.validate(choices.model_dump(),adapter.declaration_schema(bundle,inventory))
    jsonschema.validate(selection.model_dump(),adapter.binding_schema(bundle,inventory,catalog,declarations=choices))
    assert len(catalog.samples)==len(catalog.states)==5
    assert all(s.formula_raw.startswith('Y$_{1-x}$') and s.form_raw=='Polycrystalline' for s in catalog.samples)
    assert [s.conditions[0].kind for s in catalog.states]==['reported_magnetic_field']*5
    assert [s.preparation_raw for s in catalog.states[:2]] == [None,None]
    assert '$^{b}$' in catalog.states[2].preparation_raw
    assert '$^{c}$' in catalog.states[3].preparation_raw
    assert '$^{b}$' in catalog.states[4].preparation_raw
    owned,plan,proof = adapter.bind(selection,choices,relation,inventory,bundle)
    assert len(plan['items'])==70 and len(proof['operationally_unrequested_item_ids'])==65
    assert not proof['operational_holds_are_model_output']
    assert [i.id for i in adapter.requested_items(inventory.items)]==scope['item_ids']
    for clause in {palette['texts'][k]['clause_id'] for k in palette['literal']}:
        ids = [k for k in palette['literal'] if palette['texts'][k]['clause_id']==clause]
        assert {k for k in palette['catalog']['texts'] if re.fullmatch(row.id_pattern(ids),k)}==set(ids)


@pytest.mark.parametrize('mutation',['narrative_formula','sentence_method','mixed_isotope','cross_clause','empty_states','unaccounted_cell','extra_cell','kelvin_frequency'])
def test_observed_failure_classes_are_rejected(mutation):
    bundle,inventory,_,_,_,adapter,palette,raw=fixture()
    if mutation=='narrative_formula':raw['samples'][0]['formula']=dict(candidate_id='T41',end_candidate_id=None)
    elif mutation=='sentence_method':raw['protocols'][0]['method']=dict(candidate_id='T53',end_candidate_id=None)
    elif mutation=='mixed_isotope':raw['samples'][0]['isotopes'][0]['isotope_label']=dict(candidate_id='T48',end_candidate_id=None)
    elif mutation=='cross_clause':raw['protocols'][0]['method']['end_candidate_id']=next(k for k in palette['literal'] if palette['texts'][k]['clause_id']=='T54')
    elif mutation=='empty_states':raw['samples'][0]['states']=[]
    elif mutation=='unaccounted_cell':raw['samples'][0]['states'][0]['table_cell_ids']=[]
    elif mutation=='extra_cell':raw['samples'][0]['states'][0]['table_cell_ids'].append('T1:R2:C2')
    else:
        raw['protocols'][0]['parameters']=[dict(kind='frequency',name=raw['protocols'][0]['method'],
            quantity=raw['samples'][0]['states'][0]['conditions'][1]['quantity'],support=dict(candidate_id='T54',end_candidate_id=None))]
    if mutation!='unaccounted_cell':
        with pytest.raises(jsonschema.ValidationError):jsonschema.validate(raw,adapter.declaration_schema(bundle,inventory))
    with pytest.raises(ValueError):
        adapter.check_declarations(atoms.CatalogChoices.model_validate(raw),inventory,bundle,128)


@pytest.mark.parametrize('mutation',['item_ids','cell_ids','support','unrequested_owner'])
def test_scope_cannot_silently_change_the_frozen_denominator(mutation):
    bundle,inventory,_,context,scope,adapter,_,choices,rel,cat,selection=typed()
    if mutation=='unrequested_owner':
        data=selection.model_dump();key=next(i.id for i in inventory.items if i.id not in scope['item_ids'])
        data['decisions'][key]=deepcopy(next(iter(data['decisions'].values())))
        with pytest.raises(ValueError,match='owner_scope_not_closed'):
            adapter.bind(adapter.OwnerBindings.model_validate(data),choices,rel,inventory,bundle)
        return
    bad=deepcopy(scope)
    if mutation=='item_ids':bad['item_ids'].pop()
    elif mutation=='cell_ids':bad['cell_ids'][0]='T1:R99:C2'
    else:bad['support_span_ids']=['S9999']
    with pytest.raises(ValueError):row.Adapter(context,bad).verify_scope(bundle,inventory)


def responses():
    bundle,inventory,parent,context,scope,adapter,_,choices,rel,catalog,selection=typed()
    decisions={}
    for item in adapter.requested_items(inventory.items):
        owner=selection.decisions[item.id]
        q=source_candidates(item.value_raw+' K')[0]['quantity'];q['raw']=item.value_raw
        # The separate header provides K. Do not append it to the source cell.
        quantity=Quantity.model_validate(q).model_dump()
        spans=list(dict.fromkeys(item.source_span_ids+item.context_span_ids))
        decisions[item.id]=dict(decision='emitted',observation=dict(sample_id=owner.sample_id,state_id=owner.state_id,protocol_id=owner.protocol_id,
            definition=dict(criterion='unspecified',criterion_raw=None,parameters=[],evidence=[]),
            result=dict(quantity_kind='tc',quantity_name_raw=r'$^{'+('18' if item.id in {'I2','I53'} else '16')+r'}T_c$',
                quantity=quantity,origin='observed',source_role='primary',component_raw=None,interpretation_raw=None,cited_source_raw=None,
                dependencies=[],qualifiers=[],evidence=[dict(fields=['/sample_id','/state_id','/protocol_id','/quantity','/quantity_kind','/quantity_name_raw','/origin','/source_role'],span_ids=spans)])))
    links=dict(schema_version='materials-source-context-links/1',work_id=bundle.work_id,condition_supports=[],
        contexts={c.id:dict(resolution='unresolved',bindings=[],explanation='Authored bounded regression retains context for review.') for c in inventory.context_assertions})
    outputs=[choices.model_dump(),rel.model_dump(),selection.model_dump(),*[
        dict(schema_version='materials-source-item-group/1',work_id=bundle.work_id,decisions={key:decisions[key] for key in scope['item_ids'][n:n+4]})
        for n in range(0,len(scope['item_ids']),4)],links]
    return bundle,inventory,parent,context,scope,outputs


def test_durable_scoped_worker_keeps_all_items_and_replays_real_result_objects(tmp_path):
    bundle,inventory,parent,context,scope,outputs=responses()
    store=Store(tmp_path/'row-scope');provider=StageProvider(outputs)
    job=item_worker.enqueue(store,parent,workflow=row.Adapter.WORKFLOW,field_generation_policy=row.POLICY,
        source_atom_context=context,catalog_scope=scope,max_source_items=128,max_input_tokens=120000,timeout_seconds=600)
    result=run_one(store,job_id=job,provider_override=provider)
    assert result['state']=='quarantined' and provider.calls==6,result
    packet=import_packet(store,job);verify_packet(packet);receipt=packet['receipt']
    assert not receipt['staged_errors']
    assert receipt['extraction']['schema_version']=='materials-ner/10'
    assert [r['quantity']['value'] for r in receipt['extraction']['results']]==[91.19,90.99,91.35,91.16,44.63]
    assert len(receipt['staged_assembly']['source_item_ids'])==70
    assert len(receipt['staged_assembly']['row_scope']['unrequested_item_ids'])==65
    assert receipt['frozen_source_accounting']['source_cells']==58
    assert receipt['frozen_source_accounting']['materialized_cells']==5
    assert not receipt['staged_assembly']['row_scope']['full_paper_completion']
    db=ProposalDatabase(tmp_path/'private');assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    from ingestion.materials_ner.staged_revision import resolve_parent
    assert resolve_parent(packet)[0].expand(bundle).model_dump()==receipt['extraction']
    tampered=deepcopy(receipt);tampered['config']['catalog_scope']['item_ids'].pop()
    with pytest.raises(ValueError,match='scope_hash_mismatch'):item_worker.verify_receipt(tampered,bundle,packet['raw_output'])
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
