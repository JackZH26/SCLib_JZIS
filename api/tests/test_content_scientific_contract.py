"""Structural v2 wire checks only; synthetic origin IDs grant no DB authority."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from models.index_generations_v1 import PROFILE
from models.scientific_lookup import ContentScientificResultBinding, ScientificResultBinding
from models.scientific_mixed import ContentScientificMixedEvidence, ScientificMixedEvidence
from models.search import AskResponse, SearchResponse, SimilarResponse
from tests.test_scientific_lookup_contract import EVENT, GENERATION, OTHER, payload


def content_pin():
    return {'version':'index-read/2.0.0','mode':'content_snapshot','content_id':GENERATION,
        'build_id':OTHER,'activation_event_id':EVENT,'manifest_sha256':'a'*64,
        'policy_artifact_sha256':'b'*64,'profile':deepcopy(PROFILE)}


def content_binding(old, *, native):
    result=deepcopy(old)
    origin=result.pop('generation_id')
    revision=result['vector_id'][-64:]
    result.update(version='scientific-result-binding/2.0.0',content_id=GENERATION,build_id=OTHER,
        activation_event_id=EVENT,manifest_sha256='a'*64,
        policy_artifact_sha256='b'*64,content_member_record_sha256='4'*64,
        origin_kind='native_v2' if native else 'legacy_v1',origin_generation_id=None if native else origin,
        native_revision_id=OTHER if native else None,origin_record_sha256='5'*64,
        chunk_revision_sha256=revision,vector_sha256='6'*64)
    if native:result['vector_id']='rv2_'+revision
    return result


def convert(value, *, native=True):
    value=deepcopy(value)
    value['retrieval_generation']=content_pin()
    value['scientific_lookup']['scope']='declared_content_derived_extractions'
    for item in value['scientific_results']:
        item['binding']=content_binding(item['binding'],native=native)
    if value.get('scientific_mixed',{}).get('status')=='completed':
        value['scientific_mixed']['version']='scientific-mixed-evidence/2.0.0'
        if native:
            for source in value['sources']:
                source['packing_info']['chunk_id']='rv2_'+source['packing_info']['chunk_id'][-64:]
            for item in value['scientific_mixed']['associations']:
                item['source_vector_id']=value['sources'][item['source_index']-1]['packing_info']['chunk_id']
    return value


@pytest.mark.parametrize('model',[SearchResponse,AskResponse])
@pytest.mark.parametrize('native',[False,True])
def test_content_and_real_origin_identity_are_distinct_and_units_stay_unchanged(model,native):
    old=payload(model,tc='39 K',pressure='ambient pressure')
    new=convert(old,native=native)
    response=model.model_validate(new)
    assert type(response.scientific_results[0].binding) is ContentScientificResultBinding
    assert response.scientific_results[0].result.model_dump()==model.model_validate(old).scientific_results[0].result.model_dump()
    assert response.scientific_results[0].result.scientific_acceptance is False
    assert 'generation_id' not in response.scientific_results[0].binding.model_dump()
    assert model.model_validate_json(response.model_dump_json())==response


@pytest.mark.parametrize('change',[
    {'generation_id':GENERATION},{'content_id':OTHER},{'build_id':GENERATION},
    {'activation_event_id':OTHER},{'manifest_sha256':'b'*64},{'policy_artifact_sha256':'a'*64},
    {'origin_generation_id':GENERATION},{'native_revision_id':None},
    {'vector_id':'rv2_'+'0'*64},{'origin_record_sha256':'A'*64},
    {'content_member_record_sha256':None},{'scientific_acceptance':True},
    {'version':'scientific-result-binding/1.0.0'},
])
def test_content_scientific_binding_rejects_cross_version_cross_read_or_false_origin(change):
    value=convert(payload(SearchResponse))
    value['scientific_results'][0]['binding'].update(change)
    with pytest.raises(ValidationError):SearchResponse.model_validate(value)


@pytest.mark.parametrize('key',['version','origin_generation_id','native_revision_id','content_member_record_sha256'])
def test_v2_binding_never_infers_missing_identity_fields(key):
    value=convert(payload(SearchResponse))
    value['scientific_results'][0]['binding'].pop(key)
    with pytest.raises(ValidationError):SearchResponse.model_validate(value)


def test_empty_complete_content_lookup_has_no_invented_extraction_parent():
    value=convert(payload(SearchResponse))
    value['scientific_results']=[];value['scientific_lookup']['returned_count']=0
    response=SearchResponse.model_validate(value)
    assert response.scientific_results==[] and response.scientific_lookup.scientific_acceptance is False
    value['scientific_lookup']['scope']='declared_generation_derived_extractions'
    with pytest.raises(ValidationError):SearchResponse.model_validate(value)


def test_v1_response_cannot_carry_a_v2_scientific_binding():
    value=payload(SearchResponse)
    value['scientific_results'][0]['binding']=content_binding(value['scientific_results'][0]['binding'],native=False)
    with pytest.raises(ValidationError):SearchResponse.model_validate(value)


def mixed_wire():
    return json.loads((Path(__file__).resolve().parents[2]/'frontend/tests/fixtures/scientific-mixed-http.json').read_text())


@pytest.mark.parametrize('native',[False,True])
def test_explicit_v2_mixed_contract_preserves_unestablished_science_and_citation_relations(native):
    old=mixed_wire();value=convert(old,native=native)
    response=AskResponse.model_validate(value)
    assert type(response.scientific_mixed) is ContentScientificMixedEvidence
    assert response.answer_mode=='abstention' and response.tokens_used==0
    assert response.scientific_mixed.scientific_acceptance is False
    assert response.scientific_mixed.independent_support_count is None
    assert AskResponse.model_validate_json(response.model_dump_json())==response
    # V1 explicit fields serialize exactly as before; no added null origins.
    assert AskResponse.model_validate(old).model_dump(mode='json',exclude_unset=True)==old
    assert type(AskResponse.model_validate(old).scientific_mixed) is ScientificMixedEvidence
    assert all(type(item.binding) is ScientificResultBinding for item in AskResponse.model_validate(old).scientific_results)


@pytest.mark.parametrize('change',['legacy_version','missing_version','unknown_source','changed_hash',
    'restricted','stale','causal_synthesis','scientific_acceptance','legacy_read'])
def test_v2_mixed_response_rejects_cross_version_sources_and_false_science(change):
    value=convert(mixed_wire())
    if change=='legacy_version':value['scientific_mixed']['version']='scientific-mixed-evidence/1.1.0'
    elif change=='missing_version':value['scientific_mixed'].pop('version')
    elif change=='unknown_source':value['scientific_mixed']['associations'][0]['source_vector_id']='rv2_'+'0'*64
    elif change=='changed_hash':value['scientific_mixed']['associations'][0]['source_content_sha256']='0'*64
    elif change=='restricted':value['sources'][0]['evidence_provenance']['permission_status']='restricted'
    elif change=='stale':value['sources'][0]['evidence_provenance']['currentness']='stale'
    elif change=='causal_synthesis':value['answer_mode']='rag_generated'
    elif change=='scientific_acceptance':value['scientific_mixed']['scientific_acceptance']=True
    else:value['retrieval_generation']=mixed_wire()['retrieval_generation']
    with pytest.raises(ValidationError):AskResponse.model_validate(value)


def test_similar_content_identity_serializes_without_provider_generation():
    response=SimilarResponse(source_paper_id='synthetic:source',results=[],retrieval_generation=content_pin())
    assert response.retrieval_generation.mode=='content_snapshot'
    assert 'generation_id' not in response.retrieval_generation.model_dump()


@pytest.mark.parametrize('change',['read','scope','mixed'])
def test_v1_saved_answer_decoder_does_not_silently_accept_new_live_contracts(change):
    from models.answer_evidence import EXCLUDED_RESPONSE_FIELDS, validate_response
    body=AskResponse.model_validate(mixed_wire()).model_dump(mode='json',exclude=EXCLUDED_RESPONSE_FIELDS)
    if change=='read':body['retrieval_generation']=content_pin()
    elif change=='scope':body['scientific_lookup']['scope']='declared_content_derived_extractions'
    else:body['scientific_mixed']['version']='scientific-mixed-evidence/2.0.0'
    with pytest.raises(ValueError):validate_response(body)


@pytest.mark.parametrize('field',['retrieval_generation','scientific_lookup','scientific_mixed'])
@pytest.mark.parametrize('value',[None,[]])
def test_v1_saved_response_malformed_envelopes_fail_as_closed_validation_errors(field,value):
    from models.answer_evidence import EXCLUDED_RESPONSE_FIELDS,validate_response
    body=AskResponse.model_validate(mixed_wire()).model_dump(mode='json',exclude=EXCLUDED_RESPONSE_FIELDS)
    body[field]=value
    with pytest.raises(ValueError):validate_response(body)
