"""Closed v2 output capture; no persistence or scientific gold is asserted."""
from dataclasses import replace
import json
import os

import pytest

from models.answer_evidence import EXCLUDED_RESPONSE_FIELDS,validate_response as old_response
from models.content_answer_evidence import ContentAnswerEvidenceBindings,VERSION,pin_sha256,validate_body,validate_response
from models.index_read import ContentReadMetadata,retrieval_read_metadata
from models.search import AskRequest,AskResponse
from models.scientific_lookup import ScientificLookupStatus
from services import answer_evidence as old,content_answer_evidence as service,content_scientific_lookup
from tests.test_content_scientific_contract import convert
from tests.test_scientific_lookup_contract import payload
from tests.test_content_scientific_lookup import content as content
from tests.test_index_generations import db_session as db_session

vector_only=pytest.mark.skipif(os.environ.get('SCLIB_PGVECTOR_RUNTIME_TEST')!='1',reason='Requires fresh owned vector services')


def wire(native=True):
    response=AskResponse.model_validate(convert(payload(AskResponse),native=native)).model_dump(mode='json',exclude=EXCLUDED_RESPONSE_FIELDS)
    request=AskRequest(question=response['scientific_query']['raw_query']).model_dump(mode='json')
    binding=response['scientific_results'][0]['binding'];read=ContentReadMetadata.model_validate(response['retrieval_generation'])
    item={key:value for key,value in binding.items() if key not in {'version','content_id','build_id','activation_event_id',
        'manifest_sha256','policy_artifact_sha256','association_scope'}}
    item['chunk_id']=item.pop('vector_id')
    item.update(kind='scientific_result',position=1,source_snapshot_sha256='7'*64,
        selection_input_sha256='8'*64,selection_content_pin_sha256=pin_sha256(read,'synthetic-main'),
        selection_grouping_sha256='9'*64,has_evidence_pin=True)
    bindings={'version':VERSION,'mode':'content_bound','logical_index':'synthetic-main','read':response['retrieval_generation'],
        'items':[item]}
    return request,response,bindings


@pytest.mark.parametrize('native',[False,True])
def test_closed_wire_keeps_explicit_content_and_real_origin_and_refuses_v1_decoder(native):
    request,response,bindings=wire(native)
    assert validate_body(request,response,bindings)==(request,response,bindings)
    assert 'generation_id' not in bindings and 'generation_id' not in bindings['read']
    assert ContentAnswerEvidenceBindings.model_validate_json(json.dumps(bindings)).model_dump(mode='json')==bindings
    with pytest.raises(ValueError):old_response(response)


@pytest.mark.parametrize('field,value',[('origin_generation_id','00000000-0000-0000-0000-000000000000'),
    ('native_revision_id',None),('chunk_id','rv2_'+'0'*64),('has_evidence_pin',1),('selection_content_pin_sha256','0'*64),
    ('origin_record_sha256','A'*64),('content_member_record_sha256',None),('parent_result_revision_id',None)])
def test_false_origin_missing_parent_or_forged_selected_pin_is_refused(field,value):
    request,response,bindings=wire();bindings['items'][0][field]=value
    with pytest.raises(ValueError):validate_body(request,response,bindings)


@pytest.mark.parametrize('fault',['version','duplicate','drop','read','quantity','extra','order'])
def test_cross_version_and_output_inventory_mismatches_are_refused(fault):
    request,response,bindings=wire()
    if fault=='version':bindings['version']='ask-answer-evidence/1.0.0'
    elif fault=='duplicate':bindings['items']*=2
    elif fault=='drop':bindings['items']=[];bindings['mode']='no_selected_evidence'
    elif fault=='read':response['retrieval_generation']['build_id']='00000000-0000-0000-0000-000000000000'
    elif fault=='quantity':response['scientific_results'][0]['binding']['content_sha256']='0'*64
    elif fault=='extra':bindings['items'][0]['generation_id']='00000000-0000-0000-0000-000000000000'
    else:bindings['items'][0]['position']=2
    with pytest.raises(ValueError):validate_body(request,response,bindings)


def test_version_is_required_and_payload_is_bounded_before_encoding():
    request,response,bindings=wire();bindings.pop('version')
    with pytest.raises(ValueError):validate_body(request,response,bindings)
    response['answer']='x'*(1024*1024+1)
    with pytest.raises(ValueError,match='resource_limit'):validate_response(response)


async def captured(db,content):
    pin,_,_=content
    request=AskRequest(question='What is the Tc of MgB2?')
    from services.scientific_query import interpret_scientific_query
    query=interpret_scientific_query(request.question)
    inputs=(await content_scientific_lookup.prepare_content_scientific_lookup(db,pin,query)).consume()
    response=AskResponse(answer='Synthetic reported extraction records, not independent scientific support.',sources=[],
        tokens_used=0,query_time_ms=1,citation_valid=True,retrieval_generation=retrieval_read_metadata(pin),
        scientific_query=query,scientific_lookup=inputs.outcome.status,scientific_results=inputs.outcome.results)
    capture=service.capture_inputs(request=request,backend_pin=pin,scientific_inputs=inputs)
    return capture,response,inputs,request


@vector_only
@pytest.mark.asyncio
async def test_capture_real_native_legacy_parent_bindings_and_preserve_v1_boundary(db_session,content):
    capture,response,inputs,_=await captured(db_session,content)
    prepared=service.finish_capture(capture,response);document=prepared.document
    assert {row['origin_kind'] for row in document['bindings']['items']}=={'legacy_v1','native_v2'}
    assert document['response']['scientific_results']==[row.model_dump(mode='json') for row in inputs.outcome.results]
    assert not {'remaining','guest_remaining','history'}&set(document['response'])
    with pytest.raises(ValueError):await old.receipt_fields(db_session,prepared)
    document['bindings']['items'].clear()
    assert len(prepared.document['bindings']['items'])==2


@vector_only
@pytest.mark.asyncio
async def test_mutation_private_mac_and_final_quantity_change_cannot_rewrite_capture(db_session,content):
    capture,response,_,_=await captured(db_session,content)
    changed=json.loads(capture._json);changed['results'][0]['result']['tc']['value']=300
    with pytest.raises(ValueError):service.finish_capture(replace(capture,_json=json.dumps(changed)),response)
    value=response.model_dump(mode='json');value['scientific_results'][0]['result']['tc']['value']=300
    changed_response=AskResponse.model_validate(value)
    with pytest.raises(ValueError):service.finish_capture(capture,changed_response)


@vector_only
@pytest.mark.asyncio
async def test_scalar_tampering_with_real_parent_ids_fails_at_capture(db_session,content):
    _,_,inputs,request=await captured(db_session,content)
    value=json.loads(inputs._outcome_json);value['results'][0]['result']['tc']['value']=300
    changed=replace(inputs,_outcome_json=content_scientific_lookup._json(value))
    with pytest.raises(ValueError):service.capture_inputs(request=request,backend_pin=inputs.backend_pin,scientific_inputs=changed)


@vector_only
@pytest.mark.asyncio
async def test_final_withdrawal_drops_all_previously_selected_origin_ids(db_session,content):
    capture,response,inputs,_=await captured(db_session,content)
    response=AskResponse(answer='Selected context withheld.',sources=[],tokens_used=0,query_time_ms=1,citation_valid=False,
        retrieval_generation=response.retrieval_generation,scientific_query=response.scientific_query,
        scientific_lookup=ScientificLookupStatus(status='unavailable',scope='declared_content_derived_extractions',
            reason_codes=['retrieval_source_changed']))
    value=service.finish_capture(capture,response).document
    assert value['bindings']['mode']=='no_selected_evidence' and value['bindings']['items']==[]
    encoded=json.dumps(value)
    assert all(parent.vector_id not in encoded for parent in inputs.parents)


@vector_only
@pytest.mark.asyncio
@pytest.mark.parametrize('origin',['legacy_v1','native_v2'])
async def test_actual_source_capture_keeps_frozen_attribution_and_checks_vector_bytes(db_session,content,origin):
    from models.search import AskSource
    from models.evidence_packing import PackingCandidate
    from services import evidence_packing,retrieval_members
    from tests.test_retrieval_currentness_v2 import selected
    pin,_,_=content
    pins,chunks=await selected(db_session,pin)
    chunk=next(row for row in chunks if row.member['origin_kind']==origin)
    selected_pin=next(row for row in pins if row.chunk_id==chunk.id)
    descriptor=(await retrieval_members.resolve_evidence(db_session,pin,[chunk]))[chunk.id]
    candidate=PackingCandidate(chunk_id=chunk.id,paper_id=chunk.paper_id,
        source_snapshot_sha256=chunk.member['source_snapshot_sha256'],content_sha256=chunk.member['content_sha256'],
        accepted_work_id=None,chunk_kind=descriptor['chunk_kind'],role_hint='results')
    plan=evidence_packing.pack_evidence([candidate],cost=lambda ids:100+100*len(ids),byte_budget=4096,max_chunks=1)
    paper=service.index_retrieval.attribution(chunk)
    source=AskSource(index=1,paper_id=chunk.paper_id,arxiv_id=paper.arxiv_id,title=paper.title,
        authors_short=old.authors_short(paper.authors or []),year=paper.date_submitted.year if paper.date_submitted else None,
        section=chunk.section,snippet=old._snippet(chunk.text),evidence_provenance=descriptor,packing_info=plan.selected[0])
    request=AskRequest(question='Explain the synthetic source',max_sources=1)
    response=AskResponse(answer='Synthetic context [1].',sources=[source],tokens_used=None,query_time_ms=1,
        evidence_packing=evidence_packing.public_summary(plan),retrieval_generation=retrieval_read_metadata(pin),
        scientific_lookup=ScientificLookupStatus(scope='declared_content_derived_extractions'))
    arguments=dict(request=request,backend_pin=pin,sources=(source,),chunks=(chunk,),selection_pins=(selected_pin,))
    capture=service.capture_inputs(**arguments)
    value=service.finish_capture(capture,response).document
    assert value['bindings']['items'][0]['origin_kind']==origin
    assert value['response']['sources'][0]['title']==paper.title
    chunk.member['vector_bytes']=b'\0'*3072
    with pytest.raises(ValueError):service.capture_inputs(**arguments)
