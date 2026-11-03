"""Owned 0108 roundtrip and retained-content fence, not release approval."""
from __future__ import annotations

import tempfile
from pathlib import Path

from migration_retrieval_native import _sha, _snapshot
from test_safety import validate_test_environment, verify_postgres_identity

REVISION = "0108_retrieval_content_v2"


def empty_roundtrip(capability, engine, config):
    from alembic import command
    from migration_revision_scope import assert_revision, at_revision
    from migration_source_expressions import public_objects
    from models.retrieval_content_v2 import FUNCTION_SIGNATURES, TABLE_ORDER
    from sqlalchemy import inspect, text

    validate_test_environment()
    with at_revision(capability, engine, config, REVISION):
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert_revision(connection, REVISION)
            before = _snapshot(connection)
            assert all(not before[0][name] for name in TABLE_ORDER)
            signatures = {connection.execute(text("SELECT to_regprocedure(:signature)::text"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() for name, arguments in FUNCTION_SIGNATURES}
            assert None not in signatures
            legacy = {name: rows for name, rows in before[0].items() if name not in TABLE_ORDER}
            old_objects = ({key: value for key, value in before[1][0].items() if key not in signatures},
                           tuple(row for row in before[1][1] if row[0] not in TABLE_ORDER))
        command.downgrade(config, "0107_retrieval_native_v2")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert not set(TABLE_ORDER) & set(inspect(connection).get_table_names(schema="public"))
            assert _snapshot(connection)[0] == legacy and public_objects(connection) == old_objects
        command.upgrade(config, REVISION)
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert _snapshot(connection) == before
    return {"empty_roundtrip_preserved_all_rows_and_sql_objects": True, "revision": REVISION}


async def populated_content(capability):
    """Exercise actual services with clearly synthetic provider/test fixtures."""
    validate_test_environment()
    from sqlalchemy import text

    from models.db import get_engine, get_session_factory
    from models.retrieval_content_v2 import TABLE_ORDER
    from services import retrieval_content as content
    from tests.test_retrieval_content import legacy_content, publication

    engine = get_engine()
    try:
        with tempfile.TemporaryDirectory(prefix="content-rehearsal-") as folder:
            async with get_session_factory()() as db:
                connection = await db.connection()
                await connection.run_sync(verify_postgres_identity, capability)
                generation, base = await legacy_content(db)
                before = {name: (await db.execute(text(
                    f"SELECT to_jsonb(t)::text FROM public.{name} t ORDER BY to_jsonb(t)::text"))).scalars().all()
                    for name in ("index_generations", "index_generation_members", "index_active_pointer")}
                _, _, event = await publication(db, Path(folder))
                plan = await content.stage_native_content(db, base_content_id=base["content_id"],
                    publication_ids=[event["publication_id"]], dry_run=False)
                references = await content.source_reference_page(db, content_id=plan["content_id"])
                assert {row["origin_kind"] for row in references} == {"legacy_v1", "native_v2"}
                await content.append_content_partition(db, content_id=plan["content_id"], partition_id=0,
                    references=references, dry_run=False)
                sealed = await content.seal_content(db, content_id=plan["content_id"], dry_run=False)
                assert sealed["member_count"] == 2 and not sealed["active_pointer_changed"]
                for name, rows in before.items():
                    assert (await db.execute(text(f"SELECT to_jsonb(t)::text FROM public.{name} t ORDER BY to_jsonb(t)::text"))).scalars().all() == rows
                for table in TABLE_ORDER:
                    assert await db.scalar(text(f"SELECT bool_and(record_sha256="
                        f"public.sclib_retrieval_record_hash_v2(to_jsonb(t))) FROM public.{table} t")) is True
                await db.commit()
            return {"synthetic": True, "provider_calls_performed": False,
                    "legacy_and_native_complete_content_created": True,
                    "new_provider_resource_created_for_native_paper": False,
                    "old_generation_id": generation["generation_id"],
                    "native_content_manifest_sha256": sealed["manifest_sha256"]}
    finally:
        await engine.dispose()


def retained_history(capability, engine, config):
    from alembic import command
    from models.retrieval_content_v2 import TABLE_ORDER
    from services.schema_lifecycle import check_connection_schema

    validate_test_environment()
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = _snapshot(connection)
        assert all(before[0][name] for name in TABLE_ORDER)
    try:
        command.downgrade(config, "0107_retrieval_native_v2")
    except RuntimeError as error:
        assert "retained retrieval publication or content history" in str(error)
    else:
        raise AssertionError("Retained content downgrade must fail closed")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        after = _snapshot(connection)
        assert after == before
    return {"nonempty_downgrade_refused": True,
            "all_rows_and_sql_objects_before_sha256": _sha(before), "all_rows_and_sql_objects_after_sha256": _sha(after)}
