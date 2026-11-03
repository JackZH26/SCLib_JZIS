"""Queue roundtrip and retained migrated-schema proof on owned services only."""

def empty_roundtrip(capability,engine,config):
    from sqlalchemy import text
    from migration_revision_scope import at_revision,assert_revision
    from test_safety import verify_postgres_identity
    with at_revision(capability,engine,config,'0115_retrieval_policy_v3'):
        with engine.connect() as db:
            verify_postgres_identity(db,capability);assert_revision(db,'0115_retrieval_policy_v3')
            assert db.execute(text("SELECT to_regclass('public.retrieval_publication_jobs_v2') IS NULL")).scalar_one()
            assert db.execute(text("SELECT to_regprocedure('public.sclib_publication_queue_insert_v2()') IS NULL")).scalar_one()
    return {'empty_roundtrip_all_prior_rows_functions_preserved':True}


async def populated(capability):
    import tempfile
    from pathlib import Path
    import sqlalchemy as sa
    from models.db import get_engine,get_session_factory
    from services import retrieval_publication_queue as queue
    from tests.test_retrieval_publication_queue import queued,claim
    from test_safety import verify_postgres_identity
    engine=get_engine()
    try:
        async with get_session_factory()() as db:
            await (await db.connection()).run_sync(verify_postgres_identity,capability)
            if not await db.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')")):
                return {'actual_pgvector_runtime':False,'populated_checks':'not_run_without_owned_vector'}
            with tempfile.TemporaryDirectory(prefix='sclib-synthetic-queue-input-') as tmp:
                _,_,_,_,result=await queued(db,Path(tmp),policy_version='v2')
                leased=await claim(db,result)
                finished=await queue.record_result(db,claim_id=leased['claim_id'],outcome='retry',error_code='operator_retry',dry_run=False)
                before=(await db.execute(sa.text('SELECT epoch FROM retrieval_publication_job_fences_v2 WHERE job_id=CAST(:id AS uuid)'),{'id':leased['job_id']})).scalar_one()
                replay=await queue.record_result(db,claim_id=leased['claim_id'],outcome='retry',error_code='operator_retry',dry_run=False)
                after=(await db.execute(sa.text('SELECT epoch FROM retrieval_publication_job_fences_v2 WHERE job_id=CAST(:id AS uuid)'),{'id':leased['job_id']})).scalar_one()
                assert replay==finished and before==after
                await db.commit()
                return {'actual_pgvector_runtime':True,'job_id':leased['job_id'],'claim_id':leased['claim_id'],
                    'result_sha256':finished['record_sha256'],'committed_native_capture_and_job':True,
                    'retry_replay_no_epoch_change':True,'synthetic':True,'activated':False,'provider_calls_performed':False}
    finally:await engine.dispose()


def retained(capability,engine,config,capture):
    from alembic import command
    from migration_retrieval_native import _snapshot,_sha
    from test_safety import verify_postgres_identity
    if not capture['actual_pgvector_runtime']:return {'nonempty_check':'not_run_without_owned_vector'}
    with engine.connect() as db:verify_postgres_identity(db,capability);before=_snapshot(db)
    try:command.downgrade(config,'0115_retrieval_policy_v3')
    except RuntimeError as error:assert 'retained native publication queue history' in str(error)
    else:raise AssertionError('Retained publication work must prevent queue downgrade')
    with engine.connect() as db:verify_postgres_identity(db,capability);after=_snapshot(db)
    assert before==after
    return {'nonempty_downgrade_refused':True,'all_rows_functions_preserved':True,'before_sha256':_sha(before),'after_sha256':_sha(after)}
