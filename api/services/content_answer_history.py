"""V2 stored-byte verification; no active index, provider or current parser."""
from uuid import UUID

import sqlalchemy as sa

from models.content_answer_evidence import VERSION,SavedContentAnswerReceipt,validate_body
from models.answer_evidence import MAX_BYTES,canonical
from models.content_answer_storage_v2 import TABLE
from services import answer_evidence as legacy
from services.content_answer_evidence import PreparedContentAnswerEvidence,ContentAnswerEvidenceError


def require(condition):
    if not condition:raise ContentAnswerEvidenceError('content_answer_historical_binding_unavailable')


async def receipt_fields(db,prepared):
    require(type(prepared) is PreparedContentAnswerEvidence)
    await legacy._session(db,readonly=False)
    value=prepared.document
    row=(await db.execute(sa.text('SELECT '+','.join(
        'public.sclib_answer_evidence_canonical_v1(CAST(:'+key+' AS jsonb)) AS '+key+'_json'
        for key in ('request','response','bindings'))),
        {key:canonical(value[key]).decode() for key in ('request','response','bindings')})).mappings().one()
    result=dict(row)
    require(sum(len(result[key+'_json'].encode()) for key in ('request','response','bindings'))<=MAX_BYTES-4096)
    validate_body(**{key:legacy._json(result[key+'_json']) for key in ('request','response','bindings')})
    result.update({key+'_sha256':legacy._hash(result[key+'_json']) for key in ('request','response','bindings')})
    result.update(version=VERSION,**{key:UUID(value['bindings']['read'][key]) for key in
        ('content_id','build_id','activation_event_id')})
    return result


async def _members(db,bindings,response):
    """Verify only the saved selections; do not resolve a current pointer."""
    from services.retrieval_members import _source_sql,MAX_BYTES as MEMBER_BYTES
    from services.retrieval_backend import _phase
    items=bindings.items
    if not items:return
    ids=[item.chunk_id for item in items]
    source=_source_sql();params={'content':UUID(bindings.read.content_id),'ids':ids}
    async with _phase(db,True,{'bytea_output':'hex'}):
        q=sa.text('SELECT count(*),coalesce(sum(octet_length(reference::text)+'
            'octet_length(origin::text)+length(vector_hex)/2),0) FROM ('+source+') bounded').bindparams(sa.bindparam('ids',expanding=True))
        count,size=(await db.execute(q,params)).one()
        require(count==len(items) and size<=MEMBER_BYTES)
        q=sa.text(source).bindparams(sa.bindparam('ids',expanding=True))
        rows=(await db.execute(q,params)).mappings().all()
    by_id={row['reference']['vector_id']:row for row in rows}
    require(set(by_id)==set(ids))
    evidence_rows=(await db.execute(sa.text('SELECT to_jsonb(e) AS evidence,to_jsonb(x) AS parent,'
        'e.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(e)) AS evidence_intact,'
        'x.record_sha256=public.sclib_rag_evidence_record_hash_v1(to_jsonb(x)) AS parent_intact '
        'FROM rag_evidence_revisions e LEFT JOIN rag_extraction_revisions x ON x.id=e.parent_extraction_revision_id '
        'WHERE e.id IN :ids').bindparams(sa.bindparam('ids',expanding=True,type_=sa.Uuid())),
        {'ids':[UUID(item.evidence_revision_id) for item in items]})).mappings().all()
    evidence_by_id={row['evidence']['id']:row for row in evidence_rows}
    for item in items:
        row=by_id[item.chunk_id];ref,origin=row['reference'],row['origin']
        require(row['intact'] is True and ref['record_sha256']==item.content_member_record_sha256
            and ref['content_id']==bindings.read.content_id and ref['vector_id']==item.chunk_id)
        require(all(ref[key]==getattr(item,key) for key in ('paper_id','origin_kind','origin_generation_id',
            'native_revision_id','origin_record_sha256','content_sha256','vector_sha256','chunk_revision_sha256')))
        require(origin['record_sha256']==item.origin_record_sha256 and all(origin[key]==getattr(item,key)
            for key in ('paper_id','source_snapshot_sha256','content_sha256','vector_sha256','chunk_revision_sha256',
                'evidence_revision_id','evidence_record_sha256')))
        require(legacy._hash(bytes.fromhex(row['vector_hex']))==item.vector_sha256
            and legacy._hash(origin['snapshot_json']['text'])==item.content_sha256)
        observed=evidence_by_id.get(item.evidence_revision_id)
        require(observed is not None and observed['evidence_intact'] is True)
        e,parent=observed['evidence'],observed['parent']
        require(e['record_sha256']==item.evidence_record_sha256 and e['paper_id']==item.paper_id
            and e['chunk_key']==origin['chunk_key'] and e['content_sha256']==item.content_sha256
            and e['source_snapshot_sha256']==item.source_snapshot_sha256)
        if parent is None:require(item.parent_result_revision_id is None)
        else:require(observed['parent_intact'] is True and parent['id']==item.parent_result_revision_id
            and parent['record_sha256']==item.parent_result_sha256 and parent['paper_id']==item.paper_id
            and parent['source_snapshot_sha256']==item.source_snapshot_sha256)
        if item.kind=='source':
            source=response['sources'][item.position-1];paper,chunk=origin['paper_snapshot_json'],origin['snapshot_json']
            from services.authors import short as authors_short
            require(source['title']==paper['title'] and source['arxiv_id']==paper['arxiv_id']
                and source['authors_short']==authors_short(paper['authors'] or [])
                and source['year']==(int(paper['date_submitted'][:4]) if paper['date_submitted'] else None)
                and source['section']==chunk['section'] and source['snippet']==legacy._snippet(chunk['text']))
        else:
            result=response['scientific_results'][item.position-1]['result'];records=origin['snapshot_json']['materials_mentioned']
            from services.rag_evidence_contract import input_record_sha256,canonical as raw_canonical
            require(parent is not None and 0<=result['record_index']<len(records)
                and input_record_sha256(records[result['record_index']])==parent['input_record_sha256']
                and result['result_id']=='legacy-result:'+legacy._hash(raw_canonical([item.paper_id,records[result['record_index']]])))


async def verify_historical(db,storedrow):
    """Caller must authorize the owning history row in the same SQL snapshot."""
    try:
        from models.content_answer_evidence import ContentAnswerEvidenceBindings
        await legacy._session(db,readonly=True)
        row=dict(storedrow)
        required={'history_id','version','content_id','build_id','activation_event_id','request_json','response_json',
            'bindings_json','request_sha256','response_sha256','bindings_sha256','record_sha256','created_at'}
        require(set(row)==required and row['version']==VERSION)
        require(all(type(row[key+'_json']) is str for key in ('request','response','bindings')))
        require(sum(len(row[key+'_json'].encode()) for key in ('request','response','bindings'))<=MAX_BYTES)
        payload={}
        for key in ('request','response','bindings'):
            require(legacy._hash(row[key+'_json'])==row[key+'_sha256']);payload[key]=legacy._json(row[key+'_json'])
        request,response,value=validate_body(**payload)
        bindings=ContentAnswerEvidenceBindings.model_validate(value,strict=True)
        require(all(str(row[key])==getattr(bindings.read,key) for key in ('content_id','build_id','activation_event_id')))
        intact=await db.scalar(sa.text(f'SELECT record_sha256=:record AND record_sha256='
            'public.sclib_answer_evidence_record_hash_v1(to_jsonb(r)) '
            'AND request_sha256=:request AND response_sha256=:response AND bindings_sha256=:bindings '
            'AND public.sclib_content_answer_header_v2(content_id,build_id,activation_event_id,CAST(:body AS jsonb)) '
            f'FROM {TABLE} r WHERE history_id=:id'),{'id':UUID(str(row['history_id'])),'record':row['record_sha256'],
                'body':canonical(value).decode(),**{key:row[key+'_sha256'] for key in ('request','response','bindings')}})
        require(intact is True)
        await _members(db,bindings,response)
        return SavedContentAnswerReceipt(version=VERSION,history_id=str(row['history_id']),
            **{key:row[key] for key in ('record_sha256','request_sha256','response_sha256','bindings_sha256')},
            request=request,response=response,bindings=bindings).model_dump(mode='json')
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):
        raise ContentAnswerEvidenceError('content_answer_historical_verification_unavailable') from None
