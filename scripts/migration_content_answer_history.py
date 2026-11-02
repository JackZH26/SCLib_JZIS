"""Owned v2 receipt migration proof; synthetic evidence is not release approval."""
import tempfile
from pathlib import Path
from uuid import uuid4

from migration_retrieval_native import _snapshot,_sha
from test_safety import validate_test_environment,verify_postgres_identity


def empty_roundtrip(capability,engine,config):
    from migration_revision_scope import at_revision,assert_revision
    from sqlalchemy import inspect,text
    with at_revision(capability,engine,config,'0112_retrieval_keysets_v2'):
        with engine.connect() as db:
            verify_postgres_identity(db,capability);assert_revision(db,'0112_retrieval_keysets_v2')
            assert 'content_answer_evidence_receipts_v2' not in inspect(db).get_table_names(schema='public')
            assert 'content_evidence_receipt_version' not in {c['name'] for c in inspect(db).get_columns('ask_history')}
            assert db.execute(text("SELECT to_regprocedure('public.sclib_content_answer_insert_v2()') IS NULL")).scalar_one()
    return {'empty_roundtrip_all_prior_rows_functions_triggers_preserved':True}


async def populated(capability):
    import sqlalchemy as sa
    from models.db import Base,get_engine,get_session_factory
    from models.search import AskRequest,AskResponse
    from models.scientific_lookup import ScientificLookupStatus
    from models.index_read import retrieval_read_metadata
    from models.content_answer_storage_v2 import TABLE,VERSION
    from services import content_answer_evidence as capture,content_answer_history as history
    from tests.test_retrieval_members import active_content
    validate_test_environment();engine=get_engine()
    try:
        with tempfile.TemporaryDirectory(prefix='content-history-migration-') as folder:
            async with get_session_factory()() as db:
                await (await db.connection()).run_sync(verify_postgres_identity,capability)
                if not await db.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')")):
                    return {'actual_pgvector_runtime':False,'populated_checks':'not_run_without_owned_pgvector'}
                pin,_,_=await active_content(db,Path(folder),policy_version='v2');await db.commit()
                request=AskRequest(question='Unresolved synthetic history question',language='en')
                response=AskResponse(answer='No evidence selected for this synthetic question.',sources=[],
                    tokens_used=None,query_time_ms=1,retrieval_generation=retrieval_read_metadata(pin),
                    scientific_lookup=ScientificLookupStatus(scope='declared_content_derived_extractions'))
                selected=capture.capture_inputs(request=request,backend_pin=pin)
                prepared=capture.finish_capture(selected,response)
                await db.execute(sa.text('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE'))
                await db.execute(sa.text("SET LOCAL TimeZone='UTC'"));await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                fields=await history.receipt_fields(db,prepared);owner,identifier=uuid4(),uuid4()
                await db.execute(Base.metadata.tables['users'].insert().values(id=owner,email=str(owner)+'@example.test',
                    name='Synthetic migration receipt owner',is_active=True,email_verified=True))
                await db.execute(Base.metadata.tables['ask_history'].insert().values(id=identifier,user_id=owner,
                    question=request.question,answer=response.answer,sources=[],tokens_used=None,latency_ms=1,
                    language='en',content_evidence_receipt_version=VERSION))
                await db.execute(Base.metadata.tables[TABLE].insert().values(history_id=identifier,**fields));await db.commit()
                await db.execute(sa.text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                await db.execute(sa.text("SET LOCAL TimeZone='UTC'"));await db.execute(sa.text("SET LOCAL statement_timeout='5000ms'"))
                row=(await db.execute(sa.select(Base.metadata.tables[TABLE]).where(
                    Base.metadata.tables[TABLE].c.history_id==identifier))).mappings().one()
                receipt=await history.verify_historical(db,row)
                assert receipt['bindings']['mode']=='no_selected_evidence' and receipt['response']['tokens_used'] is None
                return {'actual_pgvector_runtime':True,'synthetic':True,'provider_calls_performed':False,
                    'history_id':str(identifier),'content_id':pin.content_id,'build_id':pin.build_id,
                    'saved_receipt_sha256':receipt['record_sha256'],'actual_committed_receipt_and_retained_header_verified':True}
    finally:await engine.dispose()


def retained(capability,engine,config,capture):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema
    validate_test_environment()
    if not capture['actual_pgvector_runtime']:return {'retention_check':'not_run_without_owned_pgvector'}
    with engine.connect() as db:
        verify_postgres_identity(db,capability);before=_snapshot(db)
    try:command.downgrade(config,'0112_retrieval_keysets_v2')
    except RuntimeError as error:assert 'retained content answer history' in str(error)
    else:raise AssertionError('Retained v2 answer downgrade must be refused')
    with engine.connect() as db:
        verify_postgres_identity(db,capability);db.rollback()
        assert check_connection_schema(db)['status']=='compatible'
        after=_snapshot(db);assert after==before
    return {'nonempty_downgrade_refused':True,'all_prior_rows_functions_triggers_preserved':True,
        'before_sha256':_sha(before),'after_sha256':_sha(after)}
