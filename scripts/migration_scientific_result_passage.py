"""0078 round trip and retained review history on owned synthetic services."""
from __future__ import annotations

from test_safety import validate_test_environment, verify_postgres_identity
from migration_legacy_corpus import TABLES as LEGACY_CORPUS_TABLES

TABLE = "scientific_result_passage_links"


def snapshot(connection, *, old_only=True):
    from sqlalchemy import inspect, text

    return {
        name: connection.execute(text(
            f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text')).scalars().all()
        for name in inspect(connection).get_table_names(schema="public")
        if not old_only or name not in {TABLE, "alembic_version", *LEGACY_CORPUS_TABLES}
    }


def objects(connection):
    from models.scientific_result_passage_v1 import FUNCTIONS
    from sqlalchemy import text

    functions = tuple(connection.execute(text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
        {"signature": f"public.{name}({arguments})"}).scalar_one_or_none() for name, arguments in FUNCTIONS)
    triggers = tuple(connection.execute(text("""SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger
        WHERE tgrelid=to_regclass('public.scientific_result_passage_links') AND NOT tgisinternal
        ORDER BY tgname""")).all())
    return functions, triggers


def empty_roundtrip(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0
        before, definitions = snapshot(connection), objects(connection)
        assert all(definitions[0]) and len(definitions[1]) == 3
    command.downgrade(config, "0077_ml_pilot_attestations")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("0078 API must refuse 0077 schema")
        verify_postgres_identity(connection, capability)
        assert TABLE not in inspect(connection).get_table_names(schema="public")
        assert snapshot(connection) == before
        assert objects(connection) == ((None, None, None), ())
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before
        assert objects(connection) == definitions


async def populated(capability):
    validate_test_environment()
    from uuid import uuid4
    from models.db import _to_async_dsn
    from services import rag_evidence, scientific_result_passage as service
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_rag_evidence import seed, chunk_row
    from tests.test_research_freeze import add, state
    from tests.test_research_publication import actors

    engine = create_async_engine(_to_async_dsn(capability.database_url),
        isolation_level="SERIALIZABLE", poolclass=NullPool)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await (await db.connection()).run_sync(lambda c: verify_postgres_identity(c, capability))
            await db.execute(text("SET LOCAL statement_timeout='5000ms'"))
            await db.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            people = await actors(db)
            chunk, candidate = await seed(db)
            parent = await rag_evidence.register_chunk_evidence(db, chunk_id=chunk, candidate=candidate, dry_run=False)
            paper = (await chunk_row(db, chunk)).paper_id
            original = "synthetic-link-passage:" + uuid4().hex
            await add(db, "chunks", id=original, paper_id=paper, text="Synthetic passage for migration only.", materials_mentioned=[])
            passage = await rag_evidence.register_chunk_evidence(db, chunk_id=original, candidate={
                "version": candidate["version"], "chunk_kind": "original_passage",
                "source_locator": {"section": "Synthetic Results", "page": 1}}, dry_run=False)
            context = await service.action_context(db, actor_user_id=people["reviewer"],
                parent_result_revision_id=parent["parent_result_revision_id"],
                source_evidence_revision_id=passage["evidence_revision_id"])
            request = service.request_from_context(context, request_key="synthetic-migration-link", action="establish")
            before = await state(db)
            preview = await service.review(db, actor_user_id=people["reviewer"], request=request)
            assert await state(db) == before
            first = await service.review(db, actor_user_id=people["reviewer"], request=request,
                expected_preview_sha256=preview["preview_sha256"], dry_run=False)
            pairs = [(parent["parent_result_revision_id"], passage["evidence_revision_id"])]
            assert (await service.resolve_current_links(db, pairs))[pairs[0]]["bridge_revision_id"] == first["bridge_revision_id"]
            context = await service.action_context(db, actor_user_id=people["reviewer"],
                parent_result_revision_id=pairs[0][0], source_evidence_revision_id=pairs[0][1])
            withdraw = service.request_from_context(context, request_key="synthetic-migration-withdraw", action="withdraw")
            preview_withdraw = await service.review(db, actor_user_id=people["reviewer"], request=withdraw)
            await service.review(db, actor_user_id=people["reviewer"], request=withdraw,
                expected_preview_sha256=preview_withdraw["preview_sha256"], dry_run=False)
            after = await state(db)
            replay = await service.review(db, actor_user_id=people["reviewer"], request=request,
                expected_preview_sha256=preview["preview_sha256"], dry_run=False)
            assert replay["replayed"] and replay["bridge_record_sha256"] == first["bridge_record_sha256"]
            assert await service.resolve_current_links(db, pairs) == {}
            assert await state(db) == after and len(after[TABLE]) == 2
            await db.commit()
    finally:
        await engine.dispose()


def retained_history(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import check_connection_schema

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before, definitions = snapshot(connection, old_only=False), objects(connection)
        assert len(before[TABLE]) == 2
    try:
        command.downgrade(config, "0077_ml_pilot_attestations")
    except RuntimeError as exc:
        assert "immutable reviewed links exist" in str(exc)
    else:
        raise AssertionError("0078 downgrade must retain reviewed link history")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection, old_only=False) == before and objects(connection) == definitions
