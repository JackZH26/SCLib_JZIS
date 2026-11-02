"""Separate policy-only migration proof; legacy histories are not rewritten."""
from uuid import UUID,uuid4


def empty_roundtrip(capability,engine,config):
    from sqlalchemy import text
    from migration_revision_scope import at_revision,assert_revision
    from test_safety import verify_postgres_identity
    with at_revision(capability,engine,config,'0114_bounded_validation_v3'):
        with engine.connect() as db:
            verify_postgres_identity(db,capability);assert_revision(db,'0114_bounded_validation_v3')
            assert db.execute(text("SELECT to_regprocedure('public.sclib_retrieval_policy_build_v3()') IS NULL")).scalar_one()
            assert db.execute(text("SELECT tgfoid='public.sclib_retrieval_backend_insert_v2()'::regprocedure::oid FROM pg_trigger "
                "WHERE tgrelid='public.retrieval_backend_builds_v2'::regclass AND tgname='retrieval_backend_v2_insert'")).scalar_one()
    return {'empty_roundtrip_all_rows_and_old_functions_preserved':True}


async def populated(capability):
    import sqlalchemy as sa
    from models.db import get_engine,get_session_factory
    from models.retrieval_policy_v3 import POLICY,POLICY_SHA256
    from services import retrieval_backend as backend
    from tests.test_retrieval_content import legacy_content
    from test_safety import verify_postgres_identity
    engine=get_engine()
    try:
        async with get_session_factory()() as db:
            await (await db.connection()).run_sync(verify_postgres_identity,capability)
            if not await db.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')")):
                return {'actual_pgvector_runtime':False,'populated_checks':'not_run_without_owned_vector'}
            _,content=await legacy_content(db);identifier=str(uuid4())
            await backend.stage_build(db,build_id=identifier,content_id=content['content_id'],image_digest='sha256:'+'a'*64,
                implementation_revision='b'*40,dry_run=False)
            row=await backend._existing(db,'retrieval_backend_builds_v2',{'id':UUID(identifier)})
            assert row['policy']==POLICY and row['policy_artifact_sha256']==POLICY_SHA256
            await db.commit()
            return {'actual_pgvector_runtime':True,'build_id':identifier,'policy_sha256':POLICY_SHA256,
                'synthetic':True,'activated':False,'provider_calls_performed':False}
    finally:await engine.dispose()


def retained(capability,engine,config,capture):
    from alembic import command
    from migration_retrieval_native import _snapshot,_sha
    from test_safety import verify_postgres_identity
    if not capture['actual_pgvector_runtime']:return {'nonempty_check':'not_run_without_owned_vector'}
    with engine.connect() as db:verify_postgres_identity(db,capability);before=_snapshot(db)
    try:command.downgrade(config,'0114_bounded_validation_v3')
    except RuntimeError as error:assert 'retained query-policy-v3 builds' in str(error)
    else:raise AssertionError('Retained policy-v3 builds must prevent downgrade')
    with engine.connect() as db:verify_postgres_identity(db,capability);after=_snapshot(db)
    assert before==after
    return {'nonempty_downgrade_refused':True,'all_rows_functions_triggers_preserved':True,'before_sha256':_sha(before),'after_sha256':_sha(after)}
