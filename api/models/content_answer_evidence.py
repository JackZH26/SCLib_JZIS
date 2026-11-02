"""Closed v2 saved-answer bytes; structural validation is not storage authority."""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field,field_validator,model_validator

from models.answer_evidence import Closed,EXCLUDED_RESPONSE_FIELDS,canonical,validate_request
from models.index_read import ContentReadMetadata
from models.search import AskResponse

VERSION='ask-answer-evidence/2.0.0'
SHA=r'^[0-9a-f]{64}$'


def _uuid(value):
    if value is not None and str(UUID(value))!=value:raise ValueError('content_answer_evidence_uuid')
    return value


def private_pin(read,logical_index):
    return {'version':'sclib-retrieval-pin/2.0.0','logical_index':logical_index,
        **{key:getattr(read,key) for key in ('content_id','build_id','activation_event_id','manifest_sha256','policy_artifact_sha256')},
        'profile':read.profile.model_dump(mode='json')}


def pin_sha256(read,logical_index):
    return hashlib.sha256(json.dumps(private_pin(read,logical_index),sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class ContentAnswerEvidenceItem(Closed):
    kind: Literal['source','scientific_result']
    position: int=Field(ge=1,le=20)
    paper_id: str=Field(min_length=1,max_length=100)
    chunk_id: str=Field(pattern=r'^(ig62_[0-9a-f]{32}_|rv2_)[0-9a-f]{64}$')
    content_sha256: str=Field(pattern=SHA)
    content_member_record_sha256: str=Field(pattern=SHA)
    origin_kind: Literal['legacy_v1','native_v2']
    origin_generation_id: str|None
    native_revision_id: str|None
    origin_record_sha256: str=Field(pattern=SHA)
    chunk_revision_sha256: str=Field(pattern=SHA)
    vector_sha256: str=Field(pattern=SHA)
    source_snapshot_sha256: str=Field(pattern=SHA)
    evidence_revision_id: str
    evidence_record_sha256: str=Field(pattern=SHA)
    parent_result_revision_id: str|None
    parent_result_sha256: str|None=Field(pattern=SHA)
    selection_input_sha256: str=Field(pattern=SHA)
    selection_content_pin_sha256: str=Field(pattern=SHA)
    selection_grouping_sha256: str=Field(pattern=SHA)
    has_evidence_pin: Literal[True]

    @field_validator('origin_generation_id','native_revision_id','evidence_revision_id','parent_result_revision_id')
    @classmethod
    def identifiers(cls,value):return _uuid(value)

    @field_validator('has_evidence_pin',mode='before')
    @classmethod
    def real_boolean(cls,value):
        if value is not True:raise ValueError('content_answer_evidence_exact_boolean_required')
        return value

    @model_validator(mode='after')
    def exact_origin(self):
        if self.origin_kind=='legacy_v1':
            if self.origin_generation_id is None or self.native_revision_id is not None:
                raise ValueError('content_answer_evidence_legacy_origin')
            expected='ig62_'+UUID(self.origin_generation_id).hex+'_'+self.chunk_revision_sha256
        else:
            if self.native_revision_id is None or self.origin_generation_id is not None:
                raise ValueError('content_answer_evidence_native_origin')
            expected='rv2_'+self.chunk_revision_sha256
        if self.chunk_id!=expected:raise ValueError('content_answer_evidence_revision_identity')
        if (self.parent_result_revision_id is None)!=(self.parent_result_sha256 is None):
            raise ValueError('content_answer_evidence_parent_pair')
        if self.kind=='scientific_result' and self.parent_result_revision_id is None:
            raise ValueError('content_answer_evidence_result_parent_required')
        return self


class ContentAnswerEvidenceBindings(Closed):
    version: Literal['ask-answer-evidence/2.0.0']
    mode: Literal['no_selected_evidence','content_bound']
    logical_index: str=Field(pattern=r'^[A-Za-z0-9._-]{1,160}$')
    read: ContentReadMetadata
    items: list[ContentAnswerEvidenceItem]=Field(max_length=20)

    @model_validator(mode='after')
    def exact_inventory(self):
        expected_mode='content_bound' if self.items else 'no_selected_evidence'
        if (self.mode!=expected_mode or len({row.chunk_id for row in self.items})!=len(self.items)
                or self.items!=sorted(self.items,key=lambda row:(row.kind!='source',row.position))):
            raise ValueError('content_answer_evidence_inventory')
        digest=pin_sha256(self.read,self.logical_index)
        for kind in ('source','scientific_result'):
            positions=[row.position for row in self.items if row.kind==kind]
            if positions!=list(range(1,len(positions)+1)):raise ValueError('content_answer_evidence_positions')
        if any(row.selection_content_pin_sha256!=digest for row in self.items):
            raise ValueError('content_answer_evidence_selected_pin_mismatch')
        return self


def validate_response(value):
    canonical(value)
    if type(value) is not dict or set(value)!=set(AskResponse.model_fields)-EXCLUDED_RESPONSE_FIELDS:
        raise ValueError('content_answer_evidence_response_fields')
    read,lookup,mixed=(value[key] for key in ('retrieval_generation','scientific_lookup','scientific_mixed'))
    if (any(type(item) is not dict for item in (read,lookup,mixed))
            or read.get('version')!='index-read/2.0.0' or read.get('mode')!='content_snapshot'
            or lookup.get('scope')!='declared_content_derived_extractions'
            or mixed.get('version')!='scientific-mixed-evidence/2.0.0' and not (
                mixed.get('status')=='not_requested' and mixed.get('version') in
                {'scientific-mixed-evidence/1.0.0','scientific-mixed-evidence/1.1.0'})):
        raise ValueError('content_answer_evidence_response_version')
    result=AskResponse.model_validate(value,strict=True).model_dump(mode='json',exclude=EXCLUDED_RESPONSE_FIELDS)
    if canonical(result)!=canonical(value):raise ValueError('content_answer_evidence_response_coercion')
    if len(result['sources'])+len(result['scientific_results'])>20:raise ValueError('content_answer_evidence_selection_limit')
    return result


def validate_body(request,response,bindings):
    request=validate_request(request);response=validate_response(response)
    model=ContentAnswerEvidenceBindings.model_validate(bindings,strict=True)
    if len(model.items)>request['max_sources']:raise ValueError('content_answer_evidence_requested_limit')
    if canonical(model.read.model_dump(mode='json'))!=canonical(response['retrieval_generation']):
        raise ValueError('content_answer_evidence_response_read_mismatch')
    if response['scientific_query'] is not None and response['scientific_query']['raw_query']!=request['question']:
        raise ValueError('content_answer_evidence_question_mismatch')
    sources=[row for row in model.items if row.kind=='source'];results=[row for row in model.items if row.kind=='scientific_result']
    if len(sources)!=len(response['sources']) or len(results)!=len(response['scientific_results']):
        raise ValueError('content_answer_evidence_output_inventory')
    evidence_keys=('content_sha256','evidence_revision_id','evidence_record_sha256','parent_result_revision_id','parent_result_sha256')
    for item,source in zip(sources,response['sources'],strict=True):
        packing,evidence=source['packing_info'],source['evidence_provenance']
        if (source['index']!=item.position or source['paper_id']!=item.paper_id or packing is None
                or packing['chunk_id']!=item.chunk_id or packing['position']!=item.position
                or packing['source_snapshot_sha256']!=item.source_snapshot_sha256
                or not evidence or any(evidence[key]!=getattr(item,key) for key in evidence_keys)):
            raise ValueError('content_answer_evidence_source_binding')
    for item,result in zip(results,response['scientific_results'],strict=True):
        binding=result['binding']
        if (binding['vector_id']!=item.chunk_id or any(binding[key]!=getattr(item,key) for key in (*evidence_keys,
                'paper_id','content_member_record_sha256','origin_kind','origin_generation_id','native_revision_id',
                'origin_record_sha256','chunk_revision_sha256','vector_sha256'))):
            raise ValueError('content_answer_evidence_result_binding')
    bindings=model.model_dump(mode='json');canonical({'request':request,'response':response,'bindings':bindings})
    return request,response,bindings


class SavedContentAnswerReceipt(Closed):
    version: Literal['ask-answer-evidence/2.0.0']
    history_id: str
    record_sha256: str=Field(pattern=SHA)
    request_sha256: str=Field(pattern=SHA)
    response_sha256: str=Field(pattern=SHA)
    bindings_sha256: str=Field(pattern=SHA)
    request: dict
    response: dict
    bindings: ContentAnswerEvidenceBindings

    @field_validator('history_id')
    @classmethod
    def identifier(cls,value):return _uuid(value)

    @model_validator(mode='after')
    def coherent_body(self):
        validate_body(self.request,self.response,self.bindings.model_dump(mode='json'))
        canonical(self.model_dump(mode='json'))
        return self
