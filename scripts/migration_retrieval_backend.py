"""Owned 0109 boundary/readback/fence proof; never deployment approval."""
from __future__ import annotations

from uuid import uuid4

from migration_retrieval_native import _sha, _snapshot
from test_safety import validate_test_environment, verify_postgres_identity

REVISION = "0109_retrieval_backend_v2"


def empty_roundtrip(capability, engine, config):
    from alembic import command
    from migration_revision_scope import assert_revision, at_revision
    from migration_source_expressions import public_objects
    from models.retrieval_backend_v2 import FUNCTION_SIGNATURES, TABLE_ORDER
    from sqlalchemy import inspect, text

    validate_test_environment()
    with at_revision(capability, engine, config, REVISION):
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert_revision(connection, REVISION)
            before = _snapshot(connection)
            assert all(not before[0][name] for name in TABLE_ORDER)
            assert connection.execute(text("SELECT to_regnamespace('retrieval_projection') IS NOT NULL")).scalar_one()
            signatures = {connection.execute(text("SELECT to_regprocedure(:signature)::text"),
                {"signature": f"public.{name}({arguments})"}).scalar_one() for name, arguments in FUNCTION_SIGNATURES}
            assert None not in signatures
            legacy = {name: rows for name, rows in before[0].items() if name not in TABLE_ORDER}
            old_objects = ({key: value for key, value in before[1][0].items() if key not in signatures},
                           tuple(row for row in before[1][1] if row[0] not in TABLE_ORDER))
        command.downgrade(config, "0108_retrieval_content_v2")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert not set(TABLE_ORDER) & set(inspect(connection).get_table_names(schema="public"))
            assert connection.execute(text("SELECT to_regnamespace('retrieval_projection') IS NULL")).scalar_one()
            assert _snapshot(connection)[0] == legacy and public_objects(connection) == old_objects
        command.upgrade(config, REVISION)
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert _snapshot(connection) == before
    return {"empty_roundtrip_preserved_all_rows_and_sql_objects": True, "revision": REVISION,
            "reserved_private_schema_empty_boundary_verified": True}


async def populated_backend(capability):
    validate_test_environment()
    from sqlalchemy import text

    from models.db import get_engine, get_session_factory
    from services import retrieval_backend as backend
    from tests.test_retrieval_content import legacy_content

    engine = get_engine()
    try:
        async with get_session_factory()() as db:
            connection = await db.connection()
            await connection.run_sync(verify_postgres_identity, capability)
            available = await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.7')"))
            if not available:
                return {"actual_pgvector_runtime": False,
                        "populated_backend_checks": "not_run_without_owned_pgvector_runtime"}
            _, content = await legacy_content(db)
            async def legacy_rows():
                return {name: (await db.execute(text(f"SELECT to_jsonb(t)::text FROM public.{name} t "
                    "ORDER BY to_jsonb(t)::text"))).scalars().all() for name in (
                        "index_generations", "index_generation_members", "index_activation_events", "index_active_pointer")}
            before = await legacy_rows()
            identifier, validation = str(uuid4()), str(uuid4())
            await backend.stage_build(db, build_id=identifier, content_id=content["content_id"],
                image_digest="sha256:" + "a" * 64, implementation_revision="b" * 40, dry_run=False,policy_version='v2')
            await backend.create_projection(db, build_id=identifier, dry_run=False)
            await backend.copy_partition(db, build_id=identifier, partition_id=0, dry_run=False)
            await backend.build_small_projection_graph(db, build_id=identifier, dry_run=False)
            seal = await backend.seal_projection(db, build_id=identifier, dry_run=False)
            result = await backend.validate_projection(db, build_id=identifier, validation_id=validation, dry_run=False)
            assert result["outcome"] == "validated" and result["source_member_count"] == result["projection_member_count"] == 1
            assert not result["missing_count"] and not result["extra_count"] and not result["mismatch_count"]
            assert result["content_manifest_intact"] and not result["active_pointer_changed"]
            assert await legacy_rows() == before
            await db.commit()
            return {"actual_pgvector_runtime": True, "synthetic": True, "provider_calls_performed": False,
                    "image_signature_verified": False, "build_id": identifier,
                    "physical_table_oid": seal["table_oid"], "physical_index_oid": seal["index_oid"],
                    "validation_id": validation, "actual_binary_readback_validated": True,
                    "public_legacy_generations_and_pointers_unchanged": True}
    finally:
        await engine.dispose()


def retained_history(capability, engine, config, capture):
    from alembic import command
    from models.retrieval_backend_v2 import TABLE_ORDER
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import text

    validate_test_environment()
    if not capture["actual_pgvector_runtime"]:
        return {"nonempty_downgrade_check": "not_run_without_owned_pgvector_runtime"}
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = _snapshot(connection)
        assert all(before[0][name] for name in TABLE_ORDER)
        vector_sql = f"SELECT encode(digest(substring(vector_send(embedding) FROM 5),'sha256'),'hex') " \
                     f"FROM retrieval_projection.b_{capture['build_id'].replace('-', '')} ORDER BY vector_id"
        vectors_before = connection.execute(text(vector_sql)).scalars().all()
    try:
        command.downgrade(config, "0108_retrieval_content_v2")
    except RuntimeError as error:
        assert "retained retrieval build/seal/validation history" in str(error)
    else:
        raise AssertionError("Retained backend downgrade must fail closed")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        after = _snapshot(connection)
        assert before == after
        assert connection.execute(text(vector_sql)).scalars().all() == vectors_before
        assert connection.execute(text("SELECT to_regclass(:name)::oid"),
            {"name": "retrieval_projection.b_" + capture["build_id"].replace("-", "")}).scalar_one() == capture["physical_table_oid"]
    return {"nonempty_downgrade_refused": True, "private_projection_bytes_and_identity_preserved": True,
            "all_rows_and_sql_objects_before_sha256": _sha(before), "all_rows_and_sql_objects_after_sha256": _sha(after)}
