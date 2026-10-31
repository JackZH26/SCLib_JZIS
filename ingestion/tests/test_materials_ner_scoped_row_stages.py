"""Authored source regressions; these fixtures do not constitute independent Gold."""
from copy import deepcopy
from functools import lru_cache
import json

import jsonschema
import pytest

from ingestion.materials_ner import scoped_row_stages as row, compact_context as contexts
from ingestion.materials_ner import source_atoms as atoms, item_stages as items, item_worker
from ingestion.materials_ner.contract import canonical, digest
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.inventory import source_text
from ingestion.materials_ner.proposals import import_packet, verify_packet, ProposalDatabase
from ingestion.materials_ner.store import Store
from ingestion.materials_ner.worker import run_one
from test_materials_ner_item_stages import StageProvider
from test_materials_ner_positioned_row_stages import prepared as previous_prepared


@lru_cache(maxsize=1)
def prepared():
    b,i,parent,c,scope,_,_,_,_,_,_,old=previous_prepared()
    out=deepcopy(old);a=row.Adapter(c,scope)
    local,nonlocal_ids=a.formula_scopes(b,a.palette(b))
    out[0]['unrepresented']=[dict(source=dict(candidate_id=key,end_candidate_id=None),
        reason='This source occurrence has no verified link to the requested table row; applicability remains unresolved.')
        for key in sorted(nonlocal_ids)]
    choices=atoms.CatalogChoices.model_validate(out[0]);a.check_declarations(choices,i,b,128)
    relations=a.Relations.model_validate(out[1]);cat,_=a.project(choices,relations,b)
    out[2]['catalog_sha256']=digest(cat.model_dump())
    owners=a.OwnerBindings.model_validate(out[2]);owned,plan,_=a.bind(owners,choices,relations,i,b)
    for group in out[3:-1]:
        for decision in group['decisions'].values():
            decision['observation']['definition']['criterion_raw']=a.definition_choices(b)['T55']['quote']
    decisions={key:value for group in out[3:-1] for key,value in items.ItemGroup.model_validate(group).decisions.items()}
    graph=a.context_graph(cat,decisions,b);menu=contexts.targets(b,i,graph)
    dispositions={key:dict(resolution='unresolved',target_ids=[],
        explanation='Authored regression retains unresolved scientific applicability for independent review.')
        for key in menu['contexts']}
    key=next(key for key,value in menu['contexts'].items() if value)
    dispositions[key]=dict(resolution='carried',target_ids=[menu['contexts'][key][0]],explanation=None)
    out[-1]=dict(schema_version=contexts.VERSION,work_id=b.work_id,graph_sha256=digest(graph),
        contexts=dispositions,condition_supports=[])
    return b,i,parent,c,scope,a,choices,relations,cat,owners,plan,out,graph


def test_nonlocal_formulas_retained_without_becoming_sample_assertions():
    b,i,_,_,_,a,choices,_,cat,*_=prepared()
    compiled,proof=a.compile(choices,b)
    assert len(proof['formula_scope_accounting']['nonlocal_occurrences'])==9
    assert not proof['formula_scope_accounting']['scientific_applicability_verified']
    assert not any(s.alternative_formulas for s in choices.samples)
    assert len(choices.unrepresented)==9
    assert all(v==[] for v in proof['formula_scope_accounting']['local_alternative_choices'].values())
    jsonschema.Draft202012Validator.check_schema(a.declaration_schema(b,i))


def test_empty_only_arrays_keep_cardinality_without_provider_rejected_not():
    b,i,_,_,_,a,*_=prepared();schema=a.declaration_schema(b,i)
    arrays=[s['properties']['alternative_formulas'] for s in schema['$defs']['SampleChoice']['anyOf']]
    arrays.append(schema['$defs']['ProcedureChoice']['properties']['parameters'])
    for field in arrays:
        assert field['maxItems']==0 and field['items']=={'type':'string'}
        validator=jsonschema.Draft202012Validator(field)
        assert validator.is_valid([]) and not validator.is_valid(['unsupported'])
    def keys(value):
        if isinstance(value,dict):
            for k,v in value.items():
                yield k
                yield from keys(v)
        elif isinstance(value,list):
            for v in value:yield from keys(v)
    assert 'not' not in set(keys(schema))
    assert 'uniqueItems' not in set(keys(a.links_schema(b,i,prepared()[-1])))


@pytest.mark.parametrize('change',['nonlocal_positive','missing_occurrence','duplicate_occurrence'])
def test_formula_scope_and_accounting_reject_wrong_assertions(change):
    b,i,_,_,_,a,choices,*_=prepared();raw=choices.model_dump()
    if change=='nonlocal_positive':
        raw['samples'][2]['alternative_formulas']=[dict(formula=dict(candidate_id='A1344',end_candidate_id=None),
            basis='unresolved',context=dict(candidate_id='T73',end_candidate_id=None))]
    elif change=='missing_occurrence':raw['unrepresented'].pop()
    else:raw['unrepresented'][-1]=deepcopy(raw['unrepresented'][0])
    with pytest.raises(ValueError):a.check_declarations(atoms.CatalogChoices.model_validate(raw),i,b,128)


@pytest.mark.parametrize('change',['missing_definition','stitched_definition','backexchange_component'])
def test_item_contract_preserves_reported_definition_and_preparation_scope(change):
    b,i,_,_,_,a,_,_,cat,_,plan,out,_=prepared();group=deepcopy(out[3]);obs=group['decisions']['I1']['observation']
    if change=='missing_definition':obs['definition']['criterion_raw']=None
    elif change=='stitched_definition':obs['definition']['criterion_raw']='The magnetization intercept defines Tc.'
    else:obs['result']['component_raw']='$^{b}${\\small Back exchanged $^{18}$O$\\rightarrow$$^{16}$O sample }'
    with pytest.raises(ValueError,match='staged_positioned_item_contract_invalid'):
        a.check_group(items.ItemGroup.model_validate(group),cat,i,b,plan)


def test_definition_witnesses_only_add_source_evidence_to_unchanged_model_claims():
    b,i,_,_,_,a,_,_,cat,_,plan,out,_=prepared()
    decisions={k:v for group in out[3:-1] for k,v in items.ItemGroup.model_validate(group).decisions.items()}
    augmented,proof=a.definition_witnesses(b,decisions)
    assert row.scientific({k:v.model_dump() for k,v in decisions.items()})==row.scientific({k:v.model_dump() for k,v in augmented.items()})
    assert len(proof['entries'])==5 and proof['scientific_payload_unchanged']
    assert not proof['scientific_acceptance']
    assert all(x['source']['quote']==a.definition_choices(b)['T55']['quote'] for x in proof['entries'])
    for group in out[3:-1]:a.check_group(items.ItemGroup.model_validate(group),cat,i,b,plan)


def test_compact_context_expands_exact_frozen_targets_without_changing_graph():
    b,i,_,_,_,a,_,_,_,_,_,out,graph=prepared();before=canonical(graph)
    links,proof=a.project_contexts(contexts.Selections.model_validate(out[-1]),b,i,graph)
    assert canonical(graph)==before and proof['source_connections_verified']
    assert not proof['scientific_acceptance'] and not proof['ml_training_eligible']
    assert sum(len(c.bindings) for c in links.contexts.values())==1
    jsonschema.Draft202012Validator.check_schema(a.links_schema(b,i,graph))
    # Preserve all original source text while removing the large Cartesian menu.
    old=row.previous.Adapter.links_schema(a,b,i,graph)
    assert len(canonical(a.links_schema(b,i,graph)))<len(canonical(old))
    rendered=a.render_links(b,i,graph)
    assert rendered.endswith(source_text(b))
    catalog=source_catalog(b)
    assert all(span['text'] in rendered for span in catalog['spans'].values())


def test_context_prompt_retains_assertion_identity_as_untrusted_claims():
    b,i,_,_,_,a,_,_,_,_,_,_,graph=prepared()
    prompt=a.render_links(b,i,graph)
    rendered=json.loads(next(line[len('CONTEXTS: '):] for line in prompt.splitlines() if line.startswith('CONTEXTS: ')))
    assert 'untrusted prior model assertions' in prompt
    for entry,original in zip(rendered,i.context_assertions,strict=True):
        assert entry['id']==original.id and entry['kind']==original.kind
        assert entry['description']==original.description and entry['source_span_ids']==original.span_ids


@pytest.mark.parametrize('change',['unknown','disconnected','duplicate','graph_hash','missing_context'])
def test_compact_context_rejects_retargeting_or_omission(change):
    b,i,_,_,_,a,_,_,_,_,_,out,graph=prepared();raw=deepcopy(out[-1]);menu=contexts.targets(b,i,graph)
    key=next(k for k,v in raw['contexts'].items() if v['resolution']=='carried')
    if change=='unknown':raw['contexts'][key]['target_ids']=['F999999']
    elif change=='disconnected':
        key=next(k for k,v in menu['contexts'].items() if set(menu['targets'])-set(v))
        target=next(iter(set(menu['targets'])-set(menu['contexts'][key])))
        raw['contexts'][key]=dict(resolution='carried',target_ids=[target],explanation=None)
    elif change=='duplicate':raw['contexts'][key]['target_ids']*=2
    elif change=='graph_hash':raw['graph_sha256']='0'*64
    else:raw['contexts'].pop(key)
    with pytest.raises(ValueError,match='staged_compact_context_duplicate_target' if change=='duplicate' else None):
        a.project_contexts(contexts.Selections.model_validate(raw),b,i,graph)


def test_complete_worker_replay_revision_reconstruction_and_private_idempotency(tmp_path):
    b,i,parent,c,scope,a,_,_,_,_,_,out,_=prepared();store=Store(tmp_path/'scoped');provider=StageProvider(deepcopy(out))
    job=item_worker.enqueue(store,parent,workflow=a.WORKFLOW,field_generation_policy=a.POLICY,
        source_atom_context=c,catalog_scope=scope,max_source_items=128,max_input_tokens=120000,timeout_seconds=600)
    outcome=run_one(store,job_id=job,provider_override=provider)
    assert outcome['state']=='quarantined' and provider.calls==6,outcome
    packet=import_packet(store,job);verify_packet(packet);receipt=packet['receipt']
    assert not receipt['staged_errors'],receipt['staged_errors']
    assert receipt['config']['context_selection_version']==contexts.VERSION
    assert len(receipt['extraction']['results'])==5
    assert len(receipt['staged_assembly']['result_definition_witnesses']['entries'])==5
    assert receipt['staged_assembly']['compact_context_projection']['selection_sha256']==digest(out[-1])
    from ingestion.materials_ner.staged_revision import resolve_parent
    graph,inventory=resolve_parent(packet)
    assert graph.expand(b).model_dump()==receipt['extraction']
    db=ProposalDatabase(tmp_path/'private')
    assert db.ingest(packet)['inserted'] and not db.ingest(packet)['inserted']
    assert not packet['scientific_acceptance'] and not packet['ml_training_eligible']
