"""Owned head/rollback proof for derived native navigation; no release approval."""
from pathlib import Path
import tempfile

from migration_retrieval_native import _sha,_snapshot
from test_safety import validate_test_environment,verify_postgres_identity


def empty_roundtrip(capability,engine,config):
    from migration_revision_scope import at_revision,assert_revision
    from sqlalchemy import inspect,text
    validate_test_environment()
    with at_revision(capability,engine,config,'0110_retrieval_activation_v2'):
        with engine.connect() as db:
            verify_postgres_identity(db,capability);assert_revision(db,'0110_retrieval_activation_v2')
            assert 'retrieval_native_navigation_v2' not in inspect(db).get_table_names(schema='public')
            assert db.execute(text("SELECT to_regprocedure('public.sclib_retrieval_navigation_complete_v2()') IS NULL")).scalar_one()
    return {'empty_roundtrip_all_rows_and_sql_objects_preserved':True}


async def populated(capability):
    from models.db import get_engine,get_session_factory
    from services import retrieval_navigation,retrieval_members
    from sqlalchemy import text
    from tests.test_retrieval_members import active_content
    validate_test_environment();engine=get_engine()
    try:
        with tempfile.TemporaryDirectory(prefix='native-navigation-rehearsal-') as folder:
            async with get_session_factory()() as db:
                await (await db.connection()).run_sync(verify_postgres_identity,capability)
                if not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')")):
                    return {'actual_pgvector_runtime':False,'populated_checks':'not_run_without_owned_pgvector'}
                pin,ids,_=await active_content(db,Path(folder))
                assert {row.chunk_id for row in await retrieval_navigation.lexical_search(db,pin,'Synthetic',limit=30)}==set(ids)
                assert await retrieval_members.load_text_bindings(db,pin,ids)
                await db.commit()
            return {'actual_pgvector_runtime':True,'synthetic':True,'provider_calls_performed':False,
                'content_id':pin.content_id,'build_id':pin.build_id,'native_and_legacy_navigation_verified':True}
    finally:await engine.dispose()


def retained_active_navigation(capability,engine,config,capture):
    from alembic import command
    from sqlalchemy import text
    from services.schema_lifecycle import check_connection_schema
    validate_test_environment()
    if not capture['actual_pgvector_runtime']:return {'retention_check':'not_run_without_owned_pgvector'}
    with engine.connect() as db:
        verify_postgres_identity(db,capability);before=_snapshot(db)
        name='retrieval_projection.b_'+capture['build_id'].replace('-','')
        physical=db.execute(text('SELECT to_regclass(:name)::oid'),{'name':name}).scalar_one()
    try:command.downgrade(config,'0110_retrieval_activation_v2')
    except RuntimeError as error:assert 'active native navigation' in str(error)
    else:raise AssertionError('Active native navigation downgrade must be refused')
    with engine.connect() as db:
        verify_postgres_identity(db,capability);db.rollback()
        assert check_connection_schema(db)['status']=='compatible'
        after=_snapshot(db);assert after==before
        assert db.execute(text('SELECT to_regclass(:name)::oid'),{'name':name}).scalar_one()==physical
    return {'active_native_downgrade_refused':True,'all_rows_functions_triggers_and_physical_oid_preserved':True,
        'before_sha256':_sha(before),'after_sha256':_sha(after)}
