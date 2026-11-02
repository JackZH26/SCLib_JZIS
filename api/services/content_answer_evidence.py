"""Detached v2 final-output capture; no storage, activation or source grants."""
from __future__ import annotations

import hmac
from dataclasses import dataclass,field

from models.answer_evidence import MAX_BYTES,EXCLUDED_RESPONSE_FIELDS,canonical,validate_request
from models.content_answer_evidence import ContentAnswerEvidenceItem,ContentAnswerEvidenceBindings,VERSION,validate_body
from models.index_read import retrieval_read_metadata
from models.search import AskRequest,AskResponse,AskSource
from services import answer_evidence as legacy,index_retrieval
from services.content_scientific_lookup import ContentScientificInputs
from services.retrieval_activation import RetrievalPinV2
from services.retrieval_currentness import SelectionPin


class ContentAnswerEvidenceError(ValueError):pass


def _require(condition):
    if not condition:raise ContentAnswerEvidenceError('content_answer_evidence_binding_unavailable')


@dataclass(frozen=True,slots=True)
class CapturedContentAnswerInputs:
    _json: str=field(repr=False)
    _signature: str=field(repr=False)
    def _read(self):
        _require(type(self._json) is str and type(self._signature) is str and
            hmac.compare_digest(self._signature,legacy._seal('content-capture',self._json.encode())))
        return legacy._json(self._json)


@dataclass(frozen=True,slots=True)
class PreparedContentAnswerEvidence:
    _json: str=field(repr=False)
    _signature: str=field(repr=False)
    @property
    def document(self):
        _require(type(self._json) is str and type(self._signature) is str and
            hmac.compare_digest(self._signature,legacy._seal('content-prepared',self._json.encode())))
        value=legacy._json(self._json)
        validate_body(**value)
        return value


def _item(kind,position,member,pin,evidence,backend):
    _require(type(member) is dict and type(pin) is SelectionPin and pin.has_evidence_pin
        and pin.chunk_id==member['vector_id'] and pin.paper_id==member['paper_id']
        and pin.generation_pin_sha256==index_retrieval.pin_sha256(backend.metadata())
        and member['content_id']==backend.content_id and member['record_sha256']==member['origin_record_sha256']
        and type(evidence) is dict and evidence.get('permission_status')!='restricted'
        and evidence.get('currentness')!='stale')
    text=member['snapshot_json']['text']
    _require(type(text) is str and legacy._hash(text)==member['content_sha256'])
    if kind=='source':
        raw=member['vector_bytes']
        _require(type(raw) in {bytes,memoryview} and len(raw)==3072 and legacy._hash(bytes(raw))==member['vector_sha256'])
    values={'kind':kind,'position':position,'chunk_id':member['vector_id'],
        **{key:member[key] for key in ('paper_id','content_sha256','content_member_record_sha256','origin_kind',
            'origin_generation_id','native_revision_id','origin_record_sha256','chunk_revision_sha256',
            'vector_sha256','source_snapshot_sha256','evidence_revision_id','evidence_record_sha256')},
        **{key:evidence.get(key) for key in ('parent_result_revision_id','parent_result_sha256')},
        'selection_input_sha256':pin.input_sha256,'selection_content_pin_sha256':pin.generation_pin_sha256,
        'selection_grouping_sha256':pin.grouping_sha256,'has_evidence_pin':True}
    _require(all(evidence.get(key)==values[key] for key in ('content_sha256','evidence_revision_id','evidence_record_sha256')))
    return ContentAnswerEvidenceItem.model_validate(values,strict=True).model_dump(mode='json')


def capture_inputs(*,request,backend_pin,sources=(),chunks=(),selection_pins=(),scientific_inputs=None):
    """Capture only already selected typed inputs before a provider await.

    The MAC protects private process consistency. Actual persisted receipts
    must later verify real retained SQL rows and owner-authorized history.
    """
    try:
        _require(type(request) is AskRequest and type(backend_pin) is RetrievalPinV2
            and type(sources) is tuple and type(chunks) is tuple and type(selection_pins) is tuple
            and len(sources)==len(chunks)==len(selection_pins)<=20 and all(type(row) is AskSource for row in sources))
        request_value=validate_request(request.model_dump(mode='json'))
        read=retrieval_read_metadata(backend_pin).model_dump(mode='json')
        items=[];source_values=[];result_values=[]
        for position,(source,chunk,pin) in enumerate(zip(sources,chunks,selection_pins,strict=True),1):
            _require(type(chunk) is index_retrieval.GenerationChunk and chunk.generation_pin==backend_pin.metadata()
                and source.index==position and chunk.text==chunk.member['snapshot_json']['text'])
            legacy._source_attribution(source,chunk)
            source_values.append(source.model_dump(mode='json'))
            items.append(_item('source',position,chunk.member,pin,source.evidence_provenance,backend_pin))
        if scientific_inputs is not None:
            _require(type(scientific_inputs) is ContentScientificInputs and scientific_inputs.backend_pin==backend_pin)
            scientific_inputs.__post_init__()
            result_values=[row.model_dump(mode='json') for row in scientific_inputs.outcome.results]
            from services.scientific_query import interpret_scientific_query
            from services.scientific_query_results import select_record_results
            interpretation=interpret_scientific_query(request.question)
            for position,(result,parent) in enumerate(zip(result_values,scientific_inputs.parents,strict=True),1):
                member=parent.member
                projected=select_record_results(member['snapshot_json']['materials_mentioned'],interpretation,scope_id=parent.paper_id)
                matching=[row.model_dump(mode='json') for row in projected
                    if row.result_id==result['result']['result_id'] and row.record_index==result['result']['record_index']]
                _require(matching==[result['result']])
                items.append(_item('scientific_result',position,member,parent.selection_pin,result['binding'],backend_pin))
        bindings=ContentAnswerEvidenceBindings.model_validate({'version':VERSION,
            'mode':'content_bound' if items else 'no_selected_evidence','logical_index':backend_pin.logical_index,
            'read':read,'items':items},strict=True).model_dump(mode='json')
        _require(len(items)<=request.max_sources)
        payload=canonical({'request':request_value,'bindings':bindings,'sources':source_values,'results':result_values})
        return CapturedContentAnswerInputs(payload.decode(),legacy._seal('content-capture',payload))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):
        raise ContentAnswerEvidenceError('content_answer_evidence_capture_unavailable') from None


def finish_capture(captured,response):
    try:
        _require(type(captured) is CapturedContentAnswerInputs and type(response) is AskResponse)
        inputs=captured._read();bindings=inputs['bindings']
        value=response.model_dump(mode='json',exclude=EXCLUDED_RESPONSE_FIELDS)
        if value['sources'] or value['scientific_results']:
            _require(value['sources']==inputs['sources'] and value['scientific_results']==inputs['results'])
        else:bindings={**bindings,'mode':'no_selected_evidence','items':[]}
        request,value,bindings=validate_body(inputs['request'],value,bindings)
        payload=canonical({'request':request,'response':value,'bindings':bindings})
        _require(len(payload)<=MAX_BYTES-4096)
        return PreparedContentAnswerEvidence(payload.decode(),legacy._seal('content-prepared',payload))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):
        raise ContentAnswerEvidenceError('content_answer_evidence_final_binding_unavailable') from None
