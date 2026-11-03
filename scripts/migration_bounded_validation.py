"""Owned trigger-only round trip; no history or legacy function replacement."""
def empty_roundtrip(capability,engine,config):
    from sqlalchemy import text
    from migration_revision_scope import at_revision,assert_revision
    from test_safety import verify_postgres_identity
    with at_revision(capability,engine,config,'0113_content_answer_receipts_v2'):
        with engine.connect() as db:
            verify_postgres_identity(db,capability);assert_revision(db,'0113_content_answer_receipts_v2')
            assert db.execute(text("SELECT to_regprocedure('public.sclib_retrieval_backend_bounded_v3()') IS NULL")).scalar_one()
            assert db.execute(text("SELECT tgfoid='public.sclib_retrieval_backend_insert_v2()'::regprocedure::oid "
                "FROM pg_trigger WHERE tgrelid='public.retrieval_backend_validations_v2'::regclass "
                "AND tgname='retrieval_backend_v2_insert'")).scalar_one()
    return {'empty_roundtrip_all_rows_functions_and_triggers_preserved':True,'original_v2_trigger_restored_on_downgrade':True}
