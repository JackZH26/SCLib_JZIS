"""Provider-free v2 exact-parent lookup; never infer original scientific support."""
from __future__ import annotations

import json
from dataclasses import dataclass,field
from uuid import UUID

import sqlalchemy as sa

from models.scientific_lookup import ContentScientificResultBinding,LinkedScientificResult,ScientificLookupStatus
from models.scientific_query import ScientificQueryInterpretation
from services import index_retrieval,retrieval_currentness,retrieval_members
from services.rag_evidence_contract import input_record_sha256
from services.retrieval_activation import RetrievalPinV2,assert_current_backend
from services.retrieval_candidate import EngineeringCandidatePin,is_read_pin,current_read_pin
from services.retrieval_groups import resolve_grouping_bindings
from services.scientific_query_lookup import MAX_RESULTS,MAX_RECORDS,MAX_PREPARED_BYTES,LookupResult,PreparedScientificParent,_json
from services.scientific_query_results import select_record_results
from services.source_lifecycle import resolve_paper_lifecycle
from services.source_visibility import occurrence_visibility,project_source_occurrences,source_visibility

SCOPE='declared_content_derived_extractions'


@dataclass(frozen=True,slots=True)
class ContentScientificInputs:
    backend_pin: RetrievalPinV2 | EngineeringCandidatePin
    parents: tuple[PreparedScientificParent,...]
    _outcome_json: str=field(repr=False)

    def __post_init__(self):
        if not is_read_pin(self.backend_pin) or type(self.parents) is not tuple or len(self.parents)>MAX_RESULTS:
            raise ValueError('Exact bounded v2 scientific inputs required')
        outcome=self.outcome
        if type(self.backend_pin) is EngineeringCandidatePin and (self.parents or outcome.results):
            raise ValueError('Private candidates cannot create activation-bound scientific result bindings')
        if (outcome.status.scope!=SCOPE or outcome.status.returned_count!=len(self.parents)
                or len(outcome.results)!=len(self.parents) or outcome.status.status!='completed' and self.parents
                or outcome.status.has_more and not self.parents
                or len({row.parent_result_revision_id for row in self.parents})!=len(self.parents)
                or len({row.vector_id for row in self.parents})!=len(self.parents)):
            raise ValueError('Complete one-to-one content parent/result inventory required')
        expected=index_retrieval.pin_sha256(self.backend_pin.metadata());size=len(self._outcome_json.encode())
        for result,parent in zip(outcome.results,self.parents,strict=True):
            if type(parent) is not PreparedScientificParent or type(result.binding) is not ContentScientificResultBinding:
                raise ValueError('Exact immutable content parent/binding required')
            binding=result.binding;member=parent.member;raw=parent.raw_record;pin=parent.selection_pin
            if (any(getattr(binding,key)!=getattr(self.backend_pin,key) for key in
                    ('content_id','build_id','activation_event_id','manifest_sha256','policy_artifact_sha256'))
                    or parent.result_id!=result.result.result_id or parent.record_index!=result.result.record_index
                    or parent.parent_result_revision_id!=binding.parent_result_revision_id
                    or parent.paper_id!=binding.paper_id or parent.vector_id!=binding.vector_id
                    or pin.chunk_id!=parent.vector_id or pin.paper_id!=parent.paper_id
                    or not pin.has_evidence_pin or pin.grouping_sha256 is None or pin.generation_pin_sha256!=expected
                    or any(member[key]!=getattr(binding,key) for key in ('paper_id','vector_id','content_id',
                        'content_member_record_sha256','origin_kind','origin_generation_id','native_revision_id',
                        'origin_record_sha256','chunk_revision_sha256','vector_sha256','content_sha256',
                        'evidence_revision_id','evidence_record_sha256'))
                    or member['source_snapshot_sha256']!=parent.source_snapshot_sha256
                    or member['record_sha256']!=member['origin_record_sha256']
                    or input_record_sha256(raw)!=parent.input_record_sha256
                    or input_record_sha256(member['snapshot_json']['materials_mentioned'][parent.record_index])!=parent.input_record_sha256):
                raise ValueError('Scientific content parent/result/pin binding mismatch')
            size+=len(parent._member_json.encode())+len(parent._raw_record_json.encode())
        if size>MAX_PREPARED_BYTES:raise ValueError('Scientific content preparation byte budget exceeded')

    @property
    def outcome(self):
        value=json.loads(self._outcome_json)
        return LookupResult([LinkedScientificResult.model_validate(row) for row in value['results']],
            ScientificLookupStatus.model_validate(value['status']))

    @property
    def selection_pins(self):return tuple(parent.selection_pin for parent in self.parents)


class PreparedContentScientificLookup:
    __slots__=('_inputs',)
    def __init__(self,inputs):
        if type(inputs) is not ContentScientificInputs:raise ValueError('Validated content scientific inputs required')
        self._inputs=inputs
    def _available(self):
        if self._inputs is None:raise ValueError('Content scientific preparation has already been consumed')
        return self._inputs
    @property
    def outcome(self):return self._available().outcome
    @property
    def parents(self):return self._available().parents
    @property
    def selection_pins(self):return self._available().selection_pins
    def consume(self):
        result=self._available();self._inputs=None;return result
    def __copy__(self):raise TypeError('Content scientific preparation is a single-consumption handle')
    def __deepcopy__(self,memo):return self.__copy__()
    def __reduce_ex__(self,protocol):return self.__copy__()


def _prepared(pin,outcome,parents=()):
    return PreparedContentScientificLookup(ContentScientificInputs(pin,tuple(parents),_json({
        'results':[row.model_dump(mode='json') for row in outcome.results],
        'status':outcome.status.model_dump(mode='json')})))


def _status(**kwargs):return ScientificLookupStatus(scope=SCOPE,**kwargs)


async def _derived_ids(db,pin):
    # Drive from the derived-evidence partial index, then exact origin/content
    # reverse indexes. Legacy corpus windows cannot acquire invented parents.
    rows=(await db.execute(sa.text("""
      SELECT vector_id FROM (
        SELECT m.vector_id FROM rag_evidence_revisions e
          JOIN retrieval_native_revisions_v2 n ON n.evidence_revision_id=e.id
          JOIN retrieval_content_members_v2 m ON m.content_id=:content AND m.origin_kind='native_v2'
            AND m.native_revision_id=n.id AND m.vector_id=n.vector_id
        WHERE e.chunk_kind='derived_fact' AND e.parent_extraction_revision_id IS NOT NULL
        UNION ALL
        SELECT m.vector_id FROM rag_evidence_revisions e
          JOIN index_generation_members n ON n.evidence_revision_id=e.id
          JOIN retrieval_content_members_v2 m ON m.content_id=:content AND m.origin_kind='legacy_v1'
            AND m.origin_generation_id=n.generation_id AND m.vector_id=n.vector_id
        WHERE e.chunk_kind='derived_fact' AND e.parent_extraction_revision_id IS NOT NULL
      ) inventory ORDER BY vector_id COLLATE "C" LIMIT 1001
    """),{'content':UUID(pin.content_id)})).scalars().all()
    if len(rows)>1000 or len(set(rows))!=len(rows):raise ValueError('Complete bounded derived-parent inventory required')
    return list(rows)


async def _keyword_ids(db,pin,interpretation,filters,ids):
    if interpretation.intent!='general' or filters is None or not filters.active:return None
    remaining=list(interpretation.raw_query)
    for span in [*interpretation.formulas,*interpretation.constraints,*interpretation.evidence_constraints]:
        remaining[span.start:span.end]=[' ']*(span.end-span.start)
    keywords=''.join(remaining).strip()
    if not keywords:return None
    statement=sa.text("""
      SELECT m.vector_id FROM retrieval_content_members_v2 m
        LEFT JOIN index_generation_members old ON m.origin_kind='legacy_v1'
          AND old.generation_id=m.origin_generation_id AND old.vector_id=m.vector_id
        LEFT JOIN retrieval_native_revisions_v2 n ON m.origin_kind='native_v2' AND n.id=m.native_revision_id
      WHERE m.content_id=:content AND m.vector_id IN :ids AND
        (numnode(websearch_to_tsquery('english'::regconfig,:query))=0 OR
         to_tsvector('english'::regconfig,CASE WHEN m.origin_kind='legacy_v1' THEN
           coalesce(old.snapshot_json->>'title','')||' '||(old.snapshot_json->>'text') ELSE
           coalesce(n.snapshot_json->>'title','')||' '||(n.snapshot_json->>'text') END)
          @@ websearch_to_tsquery('english'::regconfig,:query))
    """).bindparams(sa.bindparam('ids',expanding=True))
    return set((await db.execute(statement,{'content':UUID(pin.content_id),'ids':ids,'query':keywords})).scalars())


async def prepare_content_scientific_lookup(db,pin,interpretation,*,limit=20,filters=None,
        year_min=None,year_max=None,sort='relevance'):
    """Caller-owned preparation: no commit/rollback, provider or fresh check."""
    if (not is_read_pin(pin) or type(interpretation) is not ScientificQueryInterpretation
            or db.new or db.dirty or db.deleted or type(limit) is not int or not 1<=limit<=MAX_RESULTS
            or sort not in {'relevance','date','tc'}
            or any(year is not None and (type(year) is not int or not 1<=year<=9999) for year in (year_min,year_max))
            or year_min is not None and year_max is not None and year_min>year_max):
        raise ValueError('Exact current content, interpretation, clean session and bounded request required')
    await (current_read_pin(db,pin) if type(pin) is EngineeringCandidatePin else assert_current_backend(db,pin))
    if interpretation.status!='resolved':
        return _prepared(pin,LookupResult([],_status(status='clarification_required',reason_codes=['unresolved_query_constraints'])))
    ids=await _derived_ids(db,pin)
    if not ids:
        return _prepared(pin,LookupResult([],_status(status='completed',reason_codes=['declared_content_no_extraction_parents'])))
    if type(pin) is EngineeringCandidatePin:
        raise ValueError('Positive scientific result bindings require the separately activated public contract')
    members=await retrieval_members.load_members(db,pin,ids)
    keywords=await _keyword_ids(db,pin,interpretation,filters,ids)
    evidence_ids=[UUID(row['evidence_revision_id']) for row in members]
    statement=sa.text("""SELECT e.id,e.paper_id,e.parent_extraction_revision_id,e.record_sha256 AS evidence_hash,
      p.input_record_sha256,p.record_sha256 AS parent_hash,
      e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,
      p.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(p)) AS parent_intact
      FROM rag_evidence_revisions e JOIN rag_extraction_revisions p ON p.id=e.parent_extraction_revision_id
      WHERE e.id IN :ids AND e.chunk_kind='derived_fact' AND e.paper_id=p.paper_id
        AND e.source_snapshot_sha256=p.source_snapshot_sha256""").bindparams(sa.bindparam('ids',expanding=True,type_=sa.Uuid()))
    parents={str(row['id']):row for row in (await db.execute(statement,{'ids':evidence_ids})).mappings()}
    candidates=[];record_count=0
    for member in members:
        parent=parents.get(member['evidence_revision_id'])
        if (parent is None or parent['evidence_intact'] is not True or parent['parent_intact'] is not True
                or parent['paper_id']!=member['paper_id'] or parent['evidence_hash']!=member['evidence_record_sha256']):
            raise ValueError('Scientific extraction identity cannot be verified')
        if keywords is not None and member['vector_id'] not in keywords:continue
        year=member['snapshot_json'].get('year')
        if ((year_min is not None or year_max is not None) and (type(year) is not int
                or year_min is not None and year<year_min or year_max is not None and year>year_max)):continue
        records=member['snapshot_json'].get('materials_mentioned')
        if type(records) is not list:raise ValueError('Malformed retained extraction records')
        record_count+=len(records)
        if record_count>MAX_RECORDS:raise ValueError('Complete scientific record inventory exceeds its budget')
        for result in select_record_results(records,interpretation,scope_id=member['paper_id'],filters=filters):
            if input_record_sha256(records[result.record_index])==parent['input_record_sha256']:
                candidates.append((member,parent,result))
    if sort=='date':candidates.sort(key=lambda row:row[0]['paper_snapshot_json'].get('date_submitted')
        or row[0]['paper_snapshot_json'].get('date_published') or '',reverse=True)
    elif sort=='tc':candidates.sort(key=lambda row:row[2].tc.value if row[2].tc.status=='parsed'
        and row[2].tc.relation=='exact' and not row[2].tc.approximate and row[2].tc.uncertainty is None else -1,reverse=True)
    selected_ids=list(dict.fromkeys(row[0]['vector_id'] for row in candidates))
    chunks=await retrieval_members.hydrate(db,pin,selected_ids);rows=list(chunks.values())
    evidence=await retrieval_members.resolve_evidence(db,pin,rows)
    linked=await retrieval_currentness._bounded_materials(db,[row.materials_mentioned for row in rows])
    statuses=await resolve_paper_lifecycle(db,{row.paper_id for row in rows})
    results=[];selected=[];seen=set();eligible=0
    for member,parent,result in candidates:
        chunk=chunks[member['vector_id']];descriptor=evidence[chunk.id];status=statuses.get(chunk.paper_id)
        if (descriptor['permission_status']=='restricted' or descriptor['currentness']=='stale'
                or not source_visibility(status)['reported_claim_filter_eligible']):continue
        if (descriptor['parent_result_revision_id']!=str(parent['parent_extraction_revision_id'])
                or descriptor['parent_result_sha256']!=parent['parent_hash']):raise ValueError('Exact extraction parent changed')
        occurrences,summary=project_source_occurrences(chunk.materials_mentioned,paper_status=status,
            linked_materials=linked,container_paper_id=chunk.paper_id)
        record=chunk.materials_mentioned[result.record_index]
        if input_record_sha256(record)!=parent['input_record_sha256']:raise ValueError('Exact raw extraction parent changed')
        visibility=occurrence_visibility(record,paper_status=status,container_paper_id=chunk.paper_id,
            linked_visibility=linked.get(record.get('material_id')) if type(record.get('material_id')) is str else None)
        if not visibility['reported_claim_filter_eligible']:continue
        identifier=str(parent['parent_extraction_revision_id'])
        if identifier in seen:continue
        seen.add(identifier);eligible+=1
        if len(results)>=limit:continue
        source=source_visibility(status);source['warning_codes']=sorted(set(source['warning_codes']+summary['warning_codes']))
        selected.append((member,parent,result,chunk,descriptor,occurrences,source,record))
        results.append(LinkedScientificResult(result=result,binding=ContentScientificResultBinding(
            version='scientific-result-binding/2.0.0',association_scope='derived_extraction_not_original_support',
            **{key:getattr(pin,key) for key in ('content_id','build_id','activation_event_id','manifest_sha256','policy_artifact_sha256')},
            **{key:member[key] for key in ('paper_id','vector_id','content_member_record_sha256','origin_kind',
                'origin_generation_id','native_revision_id','origin_record_sha256','chunk_revision_sha256',
                'vector_sha256','content_sha256','evidence_revision_id','evidence_record_sha256')},
            parent_result_revision_id=descriptor['parent_result_revision_id'],parent_result_sha256=descriptor['parent_result_sha256'])))
    grouping=await resolve_grouping_bindings(db,{row[3].paper_id for row in selected})
    prepared=[]
    for member,parent,result,chunk,descriptor,occurrences,visibility,record in selected:
        selected_pin=retrieval_currentness.selection_pin(chunk,material_evidence=occurrences,source_review=visibility,
            evidence=descriptor,grouping_binding=grouping[chunk.paper_id])
        prepared.append(PreparedScientificParent(result_id=result.result_id,record_index=result.record_index,
            parent_result_revision_id=str(parent['parent_extraction_revision_id']),paper_id=chunk.paper_id,vector_id=chunk.id,
            source_snapshot_sha256=member['source_snapshot_sha256'],input_record_sha256=parent['input_record_sha256'],
            selection_pin=selected_pin,_raw_record_json=_json(record),
            _member_json=_json({key:value for key,value in member.items() if key!='vector_bytes'})))
    reasons=['derived_extractions_not_independent_scientific_support']
    if keywords is not None:reasons.append('remaining_keywords_are_content_fulltext_conditions')
    if interpretation.intent in {'mixed','mechanism'}:reasons.append('explanatory_synthesis_not_performed')
    if filters is not None and filters.include_unknown_pressure and (filters.ambient_only
            or filters.pressure_min is not None or filters.pressure_max is not None):
        reasons.append('unknown_pressure_cannot_prove_requested_pressure')
    await (current_read_pin(db,pin) if type(pin) is EngineeringCandidatePin else assert_current_backend(db,pin))
    return _prepared(pin,LookupResult(results,_status(status='completed',returned_count=len(results),
        has_more=eligible>len(results),reason_codes=reasons)),prepared)


async def lookup_content_scientific_results(db,pin,interpretation,**kwargs):
    inputs=(await prepare_content_scientific_lookup(db,pin,interpretation,**kwargs)).consume()
    outcome=inputs.outcome
    if outcome.status.status!='completed':return outcome
    await db.rollback()
    if inputs.selection_pins:
        async def resolver(fresh,chunks):return await retrieval_members.resolve_evidence(fresh,pin,chunks)
        checked=await retrieval_currentness.check_selected_sources(inputs.selection_pins,backend_pin=pin,evidence_resolver=resolver)
        if checked.status!='unchanged':
            return LookupResult([],_status(status='unavailable',reason_codes=[checked.reason_code or 'scientific_lookup_currentness_unavailable']))
    await (current_read_pin(db,pin) if type(pin) is EngineeringCandidatePin else assert_current_backend(db,pin))
    return outcome
