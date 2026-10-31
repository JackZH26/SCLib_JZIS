"""Target ownership and attribution support have distinct versioned scopes."""
from copy import deepcopy

import pytest

from ingestion.materials_ner import item_ownership as owners
from ingestion.materials_ner.evidence import source_catalog
from ingestion.materials_ner.sources import Block,sha
from test_materials_ner_item_ownership import fixture,execute


def context_fixture():
    bundle,inventory,declarations,_,_,_=fixture()
    text='This additional paragraph identifies the provenance of the first assertion.'
    block=Block(id='attribution-context',document_id=bundle.documents[0].id,ordinal=len(bundle.blocks),
        locator='context:synthetic',text=text,sha256=sha(text.encode()))
    bundle.blocks.append(block)
    span=next(s for s,v in source_catalog(bundle)['spans'].items() if v['block_id']==block.id)
    inventory.items[0].context_span_ids.append(span)
    declarations['item_owners']['I1']['attribution']['source_span_ids']=[span]
    return bundle,inventory,declarations,span


def test_context_support_is_per_item_and_does_not_change_historical_v1():
    bundle,inventory,declarations,span=context_fixture();owned=owners.Declarations.model_validate(declarations)
    with pytest.raises(ValueError,match='source_disconnected'):owners.project(owned,inventory,bundle)
    plan=owners.project(owned,inventory,bundle,policy=owners.CONTEXT_POLICY)
    assert plan['schema'].endswith('/2') and plan['policy']==owners.CONTEXT_POLICY
    assert plan['items']['I1']['target_span_ids']==inventory.items[0].source_span_ids
    assert span in plan['items']['I1']['attribution_support_scope']
    assert not plan['items']['I1']['scientific_attribution_verified']
    # A different assertion has not declared this context.
    declarations['item_owners']['I2']['attribution']['source_span_ids']=[span]
    with pytest.raises(ValueError,match='source_disconnected'):
        owners.project(owners.Declarations.model_validate(declarations),inventory,bundle,policy=owners.CONTEXT_POLICY)


def test_owner_itself_still_needs_result_target_and_citation_must_be_literal():
    bundle,inventory,declarations,span=context_fixture()
    declarations['item_owners']['I1']['source_span_ids']=[span]
    with pytest.raises(ValueError,match='source_disconnected'):
        owners.project(owners.Declarations.model_validate(declarations),inventory,bundle,policy=owners.CONTEXT_POLICY)
    bundle,inventory,declarations,span=context_fixture()
    declarations['item_owners']['I1']['attribution']['cited_source_raw']='Invented external paper'
    with pytest.raises(ValueError,match='citation_not_in_source'):
        owners.project(owners.Declarations.model_validate(declarations),inventory,bundle,policy=owners.CONTEXT_POLICY)


def test_v1_prompt_and_plan_remain_independent_of_opt_in_v2():
    bundle,inventory,declarations,_,_,_=fixture();owned=owners.Declarations.model_validate(declarations)
    old=owners.project(owned,inventory,bundle);new=owners.project(owned,inventory,bundle,policy=owners.CONTEXT_POLICY)
    assert old['scientific_declarations_sha256']==new['scientific_declarations_sha256']
    assert old['schema']==owners.VERSION and 'target_span_ids' not in old['items']['I1']
    assert owners.prompt_identity(owners.POLICY)==(owners.PROMPT_VERSION,owners.PROMPT_HASH)
    assert owners.prompt_identity(owners.CONTEXT_POLICY)[1]!=owners.PROMPT_HASH
    assert 'declared context_span_ids' in owners.render_declarations(bundle,inventory,policy=owners.CONTEXT_POLICY)
    with pytest.raises(ValueError,match='policy_unknown'):owners.project(owned,inventory,bundle,policy='unknown')


@pytest.mark.parametrize('policy',[owners.POLICY,owners.CONTEXT_POLICY,owners.REFERENCE_POLICY,None])
def test_real_worker_keeps_policy_and_immutable_receipt_replay(tmp_path,policy):
    result,packet,_,_=execute(tmp_path,policy=policy)
    assert result['state']=='succeeded'
    receipt=packet['receipt']
    if policy is not None:
        assert receipt['item_owner_plan']['policy']==policy
        assert receipt['config']['prompt_version']==owners.prompt_identity(policy)[0]
    else:assert 'item_owner_plan' not in receipt


def test_reference_policy_uses_a_literal_edge_without_requiring_inventory_to_repeat_it(tmp_path):
    from test_materials_ner_reference_context import fixture as reference_fixture
    from ingestion.materials_ner.reference_context import build_index,attach_references,verified_edges
    parent,window=reference_fixture(tmp_path,citation=r'\cite{own}')
    bundle,_=attach_references(parent,window,build_index(parent));edge=verified_edges(bundle)[0]
    _,inventory,declarations,_,_,_=fixture()
    inventory.items=inventory.items[:1];item=inventory.items[0]
    item.source_span_ids=edge['citation_span_ids'];item.context_span_ids=[]
    declarations['item_owners']={'I1':declarations['item_owners']['I1']}
    decision=declarations['item_owners']['I1'];decision['source_span_ids']=edge['citation_span_ids']
    decision['attribution']['source_span_ids']=edge['entry_span_ids']
    owned=owners.Declarations.model_validate(declarations)
    with pytest.raises(ValueError,match='source_disconnected'):owners.project(owned,inventory,bundle,policy=owners.CONTEXT_POLICY)
    plan=owners.project(owned,inventory,bundle,policy=owners.REFERENCE_POLICY)
    assert plan['schema'].endswith('/3')
    assert plan['items']['I1']['literal_reference_edges']==[edge]
    assert not plan['items']['I1']['scientific_attribution_verified']
    # Merely being in the same source does not authorize unrelated context.
    unrelated=next(s for s,v in source_catalog(bundle)['spans'].items() if s not in edge['citation_span_ids']+edge['entry_span_ids'])
    item.source_span_ids=[unrelated];decision['source_span_ids']=[unrelated]
    with pytest.raises(ValueError,match='source_disconnected'):
        owners.project(owners.Declarations.model_validate(declarations),inventory,bundle,policy=owners.REFERENCE_POLICY)
