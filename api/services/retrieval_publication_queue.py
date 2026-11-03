"""Caller-owned native capture/outbox and short fenced queue operations.

No provider RPC, graph work, commit, activation or quality attestation occurs
inside these operations. Workers commit claims before external/long work.
"""
import re
from uuid import UUID,uuid5
import sqlalchemy as sa
from models.db import Base
from models.retrieval_publication_queue_v2 import TABLE_ORDER
from services.retrieval_backend import _phase
from services import retrieval_native,retrieval_content

NAMESPACE=UUID('7d0e12b7-299e-4612-8849-8c391dd5dd8c')


class PublicationQueueError(ValueError):pass


async def _existing(db,name,keys):
    if name not in TABLE_ORDER or name==TABLE_ORDER[1]:raise PublicationQueueError('Closed immutable queue relation required')
    table=Base.metadata.tables[name]
    row=(await db.execute(sa.select(table,(table.c.record_sha256==sa.func.sclib_publication_queue_hash_v2(
        sa.func.to_jsonb(table.table_valued()))).label('_intact')).where(*(table.c[k]==v for k,v in keys.items())))).mappings().one_or_none()
    if row is None:return None
    if row['_intact'] is not True:raise PublicationQueueError('Retained queue integrity mismatch')
    return {k:v for k,v in row.items() if k!='_intact'}


async def _put(db,name,keys,values):
    prior=await _existing(db,name,keys)
    if prior is not None:
        if any(prior[key]!=value for key,value in values.items()):raise PublicationQueueError('Immutable queue replay conflict')
        return prior,False
    await db.execute(Base.metadata.tables[name].insert().values(**keys,**values))
    return await _existing(db,name,keys),True


async def enqueue_publication(db,*,logical_index,publication_id,dry_run=True):
    if type(logical_index) is not str or not re.fullmatch('[A-Za-z0-9._-]{1,160}',logical_index):
        raise PublicationQueueError('Explicit bounded logical index required')
    publication=UUID(str(publication_id));identifier=uuid5(NAMESPACE,logical_index+':'+str(publication))
    async with _phase(db,dry_run) as operation:
        row,operation['changed']=await _put(db,TABLE_ORDER[0],{'id':identifier},{'logical_index':logical_index,'publication_id':publication})
    return {'job_id':str(identifier),'publication_id':str(publication),'paper_id':row['paper_id'],
        'sequence_number':row['sequence_number'],'record_sha256':row['record_sha256'],
        'dry_run':dry_run,'committed':False,'active_pointer_changed':False}


async def capture_and_enqueue(db,*,logical_index,input_arguments,items,dry_run=True):
    """Capture actual file/current chunks and enqueue in the same outer write.

    Caller persists content/evidence/embedding receipts in this transaction
    first. Any capture/enqueue failure rolls back this savepoint; the caller
    must also let its outer write fail. Independent ingestion packages can
    adopt this explicitly; it is not an implicit import across package locks.
    """
    if type(input_arguments) is not dict or 'dry_run' in input_arguments:
        raise PublicationQueueError('Explicit input observation arguments required')
    async with _phase(db,dry_run) as operation:
        observed=await retrieval_native.append_input_receipt(db,**input_arguments,dry_run=False)
        captured=await retrieval_native.append_native_revisions(db,input_receipt_id=observed['input_receipt_id'],items=items,dry_run=False)
        publication=await retrieval_content.seal_native_publication(db,paper_id=input_arguments['paper_id'],
            native_revision_ids=[row['revision_id'] for row in captured['revisions']],dry_run=False)
        job=await enqueue_publication(db,logical_index=logical_index,publication_id=publication['publication_id'],dry_run=False)
        operation['changed']=True
    return {'input':observed,'publication':publication,'job':job,'dry_run':dry_run,'committed':False,'active_pointer_changed':False}


async def claim_job(db,*,job_id,claim_id,worker_id,lease_seconds=7200,dry_run=True):
    if (type(worker_id) is not str or not re.fullmatch('[A-Za-z0-9._:-]{1,80}',worker_id)
            or type(lease_seconds) is not int or not 30<=lease_seconds<=14400):
        raise PublicationQueueError('Explicit bounded worker and lease required')
    async with _phase(db,dry_run) as operation:
        row,operation['changed']=await _put(db,TABLE_ORDER[2],{'id':UUID(str(claim_id))},
            {'job_id':UUID(str(job_id)),'worker_id':worker_id,'lease_seconds':lease_seconds})
        current=await db.scalar(sa.text('SELECT c.id=:claim AND c.lease_until>clock_timestamp() AND NOT EXISTS('
            'SELECT 1 FROM retrieval_publication_results_v2 r WHERE r.claim_id=c.id) FROM retrieval_publication_claims_v2 c '
            'WHERE c.job_id=:job ORDER BY attempt_number DESC LIMIT 1'),{'claim':row['id'],'job':row['job_id']})
    return {'claim_id':str(row['id']),'job_id':str(row['job_id']),'attempt_number':row['attempt_number'],
        'lease_until':row['lease_until'].isoformat(),'currently_usable':current is True,'record_sha256':row['record_sha256'],
        'dry_run':dry_run,'committed':False}


async def record_result(db,*,claim_id,outcome,activation_event_id=None,successor_job_id=None,error_code=None,dry_run=True):
    if type(outcome) is not str or outcome not in {'retry','published','superseded'}:raise PublicationQueueError('Closed worker outcome required')
    values={'outcome':outcome,'activation_event_id':UUID(str(activation_event_id)) if activation_event_id else None,
        'successor_job_id':UUID(str(successor_job_id)) if successor_job_id else None,'error_code':error_code}
    async with _phase(db,dry_run) as operation:
        row,operation['changed']=await _put(db,TABLE_ORDER[3],{'claim_id':UUID(str(claim_id))},values)
    return {'claim_id':str(row['claim_id']),'job_id':str(row['job_id']),'outcome':row['outcome'],
        'record_sha256':row['record_sha256'],'dry_run':dry_run,'committed':False,'active_pointer_changed':False}


async def pending_jobs(db,*,logical_index,limit=100):
    if (type(limit) is not int or not 1<=limit<=100 or type(logical_index) is not str
            or not re.fullmatch('[A-Za-z0-9._-]{1,160}',logical_index)):
        raise PublicationQueueError('Explicit logical index and bounded queue page required')
    return [dict(row) for row in (await db.execute(sa.text('SELECT j.id,j.paper_id,j.publication_id,j.sequence_number '
        'FROM retrieval_publication_jobs_v2 j JOIN retrieval_publication_job_fences_v2 f ON f.job_id=j.id '
        'WHERE j.logical_index=:logical AND NOT EXISTS(SELECT 1 FROM retrieval_publication_results_v2 r '
        "WHERE r.job_id=j.id AND r.outcome IN ('published','superseded')) AND NOT EXISTS("
        'SELECT 1 FROM retrieval_publication_claims_v2 c WHERE c.job_id=j.id AND c.lease_until>clock_timestamp() '
        'AND NOT EXISTS(SELECT 1 FROM retrieval_publication_results_v2 r WHERE r.claim_id=c.id)) '
        'ORDER BY j.sequence_number LIMIT :limit FOR UPDATE OF f SKIP LOCKED'),{'logical':logical_index,'limit':limit})).mappings()]
