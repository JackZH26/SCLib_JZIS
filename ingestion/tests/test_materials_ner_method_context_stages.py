"""Original-source regressions and authored transport, never independent Gold."""
from copy import deepcopy
from functools import lru_cache

import jsonschema
import pytest

from ingestion.materials_ner import method_context_stages as row, partial_context as contexts
from ingestion.materials_ner import compact_context, source_atoms as atoms, item_stages as items
from ingestion.materials_ner import item_worker, item_flow_v2
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_assertion_scope_stages import prepared as previous_prepared
from test_materials_ner_item_stages import StageProvider


@lru_cache(maxsize=1)
def prepared():
    b,i,parent,c,scope,_,_,_,_,old=previous_prepared()
    a=row.Adapter(c,scope);out=deepcopy(old)
    p=a.palette(b)
    # Authored source transport: a measurement clause, rather than an arbitrary
    # caption or neighboring method, supports the method vocabulary choice.
    method=next(key for key,value in p['method_offers'].items()
                if value['source']['quote']=='SQUID magnetometer')
    support=next(key for key in p['method_offers'][method]['applicability_ids']
                 if 'SQUID' in p['texts'][key]['quote'])
    out[0]['protocols'][0]['method']=dict(candidate_id=method,end_candidate_id=None)
    out[0]['protocols'][0]['applicability']=dict(candidate_id=support,end_candidate_id=None)
    declarations=atoms.CatalogChoices.model_validate(out[0]);a.check_declarations(declarations,i,b,128)
    relations=a.Relations.model_validate(out[1]);catalog,_=a.project(declarations,relations,b)
    out[2]['catalog_sha256']=digest(catalog.model_dump())
    owners=a.OwnerBindings.model_validate(out[2]);_,plan,_=a.bind(owners,declarations,relations,i,b)
    decisions={key:value for g in out[3:-1] for key,value in items.ItemGroup.model_validate(g).decisions.items()}
    graph=a.context_graph(catalog,decisions,b);menu=compact_context.targets(b,i,graph)
    selections={key:dict(resolution='unresolved',target_ids=[],
        explanation='Authored source regression; independent interpretation remains pending.')
        for key in menu['contexts']}
    method_target=next(key for key in menu['contexts']['C5'] if menu['targets'][key]['entity']=='protocol'
        and menu['targets'][key]['entity_id']=='protocol:1' and menu['targets'][key]['field']=='/method')
    selections['C5']=dict(resolution='partial',target_ids=[method_target],remaining_assertions=[dict(
        assertion='The measurement field, scan-temperature interval and operational transition definition remain unbound in this context choice.',
        source_span_ids=['S10'])])
    out[-1]=dict(schema_version=contexts.VERSION,work_id=b.work_id,graph_sha256=digest(graph),
        contexts=selections,condition_supports=[])
    return b,i,parent,c,scope,a,declarations,catalog,plan,out,graph


def test_original_muon_method_phrases_are_offered_with_original_coordinates():
    b,i,_,_,_,a,declarations,*_=prepared();p=a.palette(b)
    muon=[v for v in p['method_offers'].values() if v['method_class']=='muon_spin']
    assert {'muon-spin rotation','$\\mu$SR'} <= {v['source']['quote'] for v in muon}
    blocks={block.id:block for block in b.blocks}
    for offer in muon:
        source=offer['source'];assert blocks[source['block_id']].text[source['start_char']:source['end_char']]==source['quote']
        assert offer['applicability_ids']
    value=declarations.model_dump();method=next(k for k,v in p['method_offers'].items() if v['source']['quote']=='muon-spin rotation')
    procedure=value['protocols'][0];procedure['method']=dict(candidate_id=method,end_candidate_id=None)
    procedure['method_class']='muon_spin';procedure['observable']=None
    procedure['applicability']=dict(candidate_id=p['method_offers'][method]['applicability_ids'][0],end_candidate_id=None)
    compiled,proof=a.compile(atoms.CatalogChoices.model_validate(value),b)
    assert compiled.protocols[0].method=='muon-spin rotation'
    assert proof['method_source_choices']['lexical_compatibility_checked']
    assert not proof['method_source_choices']['scientific_applicability_verified']
    jsonschema.Draft202012Validator.check_schema(a.declaration_schema(b,i))


@pytest.mark.parametrize('variant',['muon_class_for_magnetization','heat_class_for_magnetization','other_escape','wrong_support'])
def test_mismatched_method_class_and_source_are_rejected(variant):
    b,_,_,_,_,a,declarations,*_=prepared();value=declarations.model_dump();p=a.palette(b)
    procedure=value['protocols'][0]
    if variant=='wrong_support':
        key=next(k for k,v in p['method_offers'].items() if v['method_class']=='muon_spin')
        procedure['applicability']=dict(candidate_id=p['method_offers'][key]['applicability_ids'][0],end_candidate_id=None)
    else:
        procedure['method_class']={'muon_class_for_magnetization':'muon_spin',
            'heat_class_for_magnetization':'specific_heat','other_escape':'other'}[variant]
    with pytest.raises(ValueError,match='staged_scientific_row_field_contract_invalid'):
        a.compile(atoms.CatalogChoices.model_validate(value),b)


def test_unregistered_source_method_statements_remain_representable():
    b,_,_,_,_,a,declarations,*_=prepared();p=a.palette(b)
    other=[(key,v) for key,v in p['method_offers'].items() if v['method_class']=='other']
    assert other
    key,offer=other[0];value=declarations.model_dump();procedure=value['protocols'][0]
    procedure.update(method=dict(candidate_id=key,end_candidate_id=None),method_class='other',
        applicability=dict(candidate_id=key,end_candidate_id=None),observable=None)
    compiled,_=a.compile(atoms.CatalogChoices.model_validate(value),b)
    assert compiled.protocols[0].method==offer['source']['quote']
    # The fallback is source-preserving, not a source-normalization or approval.
    assert 'unrepresentable assertion in unrepresented' in a.render_declarations(b,prepared()[1])


def test_partial_context_retains_connections_and_residual_source_without_completion():
    b,i,_,_,_,a,_,_,_,out,graph=prepared();before=canonical(graph)
    selection=contexts.Selections.model_validate(out[-1])
    links,proof=a.project_contexts(selection,b,i,graph)
    assert canonical(graph)==before
    assert links.contexts['C5'].resolution=='unresolved' and links.contexts['C5'].bindings==[]
    assert proof['partial_bindings'][0]['context_id']=='C5' and len(proof['partial_bindings'])==1
    assert proof['remaining_assertions'][0]['source_span_ids']==['S10']
    assert proof['remaining_assertions'][0]['source_quotes']
    assert proof['parent_context_ids']==[c.id for c in i.context_assertions]
    assert not proof['semantic_completeness_verified'] and not proof['scientific_acceptance']
    jsonschema.Draft202012Validator.check_schema(a.links_schema(b,i,graph))


@pytest.mark.parametrize('variant',['foreign_source','duplicate_source','empty_residual','duplicate_residual','missing_residual','missing_target','foreign_target','duplicate_target','missing_context','changed_graph'])
def test_partial_context_rejects_unbound_or_missing_review_obligations(variant):
    b,i,_,_,_,a,_,_,_,out,graph=prepared();raw=deepcopy(out[-1]);selected=raw['contexts']['C5']
    if variant=='foreign_source':selected['remaining_assertions'][0]['source_span_ids']=['S1']
    elif variant=='duplicate_source':selected['remaining_assertions'][0]['source_span_ids']*=2
    elif variant=='empty_residual':selected['remaining_assertions'][0]['assertion']=' '
    elif variant=='duplicate_residual':selected['remaining_assertions']*=2
    elif variant=='missing_residual':selected['remaining_assertions']=[]
    elif variant=='missing_target':selected['target_ids']=[]
    elif variant=='foreign_target':selected['target_ids']=['F999999']
    elif variant=='duplicate_target':selected['target_ids']*=2
    elif variant=='missing_context':raw['contexts'].pop('C8')
    else:raw['graph_sha256']='0'*64
    with pytest.raises(ValueError):a.project_contexts(contexts.Selections.model_validate(raw),b,i,graph)


def test_complete_context_remains_possible_and_its_semantics_remain_unverified():
    b,i,_,_,_,a,_,_,_,out,graph=prepared();raw=deepcopy(out[-1]);menu=compact_context.targets(b,i,graph)
    ids=[key for key in menu['contexts']['C5'] if menu['targets'][key]['field'].startswith('/conditions/')
         or (menu['targets'][key]['entity']=='definition' and menu['targets'][key]['field']=='/criterion_raw')
         or (menu['targets'][key]['entity']=='protocol' and menu['targets'][key]['field'] in ['/method','/observable'])]
    assert len(ids)>=12
    raw['contexts']['C5']=dict(resolution='carried',target_ids=ids,explanation=None)
    links,proof=a.project_contexts(contexts.Selections.model_validate(raw),b,i,graph)
    assert links.contexts['C5'].resolution=='carried' and len(links.contexts['C5'].bindings)==len(ids)
    assert proof['partial_bindings']==[] and not proof['semantic_completeness_verified']


def test_versioned_configuration_does_not_accept_the_previous_context_protocol():
    _,_,parent,c,scope,a,*_=prepared()
    config=item_worker.configuration(parent,workflow=a.WORKFLOW,field_generation_policy=a.POLICY,
        source_atom_context=c,catalog_scope=scope,max_source_items=128)
    assert config['context_selection_version']==contexts.VERSION
    assert item_flow_v2.interfaces(config)[0].POLICY==a.POLICY
    config['context_selection_version']=compact_context.VERSION
    with pytest.raises(ValueError,match='staged_compact_context_version_mismatch'):item_flow_v2.interfaces(config)


def test_authored_worker_partial_coverage_survives_replay_revision_and_import(tmp_path):
    b,_,parent,c,scope,a,_,_,_,out,_=prepared();store=Store(tmp_path/'authored');provider=StageProvider(deepcopy(out))
    job=item_worker.enqueue(store,parent,workflow=a.WORKFLOW,field_generation_policy=a.POLICY,
        source_atom_context=c,catalog_scope=scope,max_source_items=128,max_input_tokens=120000,timeout_seconds=600)
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome['state']=='quarantined' and provider.calls==6,outcome
    packet=import_packet(store,job);verify_packet(packet);receipt=packet['receipt']
    assert not receipt['staged_errors'],receipt['staged_errors']
    assert len(receipt['extraction']['results'])==5
    proof=receipt['staged_assembly']['compact_context_projection']
    assert proof['schema']==contexts.PROJECTION and len(proof['partial_bindings'])==1
    assert len(proof['remaining_assertions'])==1
    disposition=next(x for x in receipt['inventory_coverage']['context_dispositions'] if x['context_id']=='C5')
    assert disposition['resolution']=='unresolved'
    from ingestion.materials_ner.staged_revision import resolve_parent
    graph,_=resolve_parent(packet)
    assert graph.expand(b).model_dump()==receipt['extraction']
    database=ProposalDatabase(tmp_path/'private')
    assert database.ingest(packet)['inserted'] and not database.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
