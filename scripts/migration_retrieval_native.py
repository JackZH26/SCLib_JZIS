"""Actual 0107 roundtrip/fence proof in the caller's fresh owned database only."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from test_safety import validate_test_environment, verify_postgres_identity

TABLES = ("retrieval_input_receipts_v2", "retrieval_native_revisions_v2")
REVISION = "0107_retrieval_native_v2"


def _snapshot(connection):
    from migration_source_expressions import public_objects
    from sqlalchemy import inspect, text

    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    connection.execute(text("SET LOCAL bytea_output='hex'"))
    rows = {name: connection.execute(text(
        f'SELECT to_jsonb(t)::text FROM public."{name}" t ORDER BY to_jsonb(t)::text')).scalars().all()
        for name in inspect(connection).get_table_names(schema="public") if name != "alembic_version"}
    return rows, public_objects(connection)


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def empty_roundtrip(capability, engine, config):
    from alembic import command
    from migration_revision_scope import assert_revision, at_revision
    from migration_source_expressions import public_objects
    from models.retrieval_native_v2 import FUNCTION_SIGNATURES
    from sqlalchemy import inspect, text

    validate_test_environment()
    with at_revision(capability, engine, config, REVISION):
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert_revision(connection, REVISION)
            before = _snapshot(connection)
            assert all(not before[0][name] for name in TABLES)
            signatures = {connection.execute(text("SELECT to_regprocedure(:signature)::text"),
                {"signature": f"public.{name}({arguments})"}).scalar_one()
                for name, arguments in FUNCTION_SIGNATURES}
            assert None not in signatures
            legacy = {name: rows for name, rows in before[0].items() if name not in TABLES}
            old_objects = ({key: value for key, value in before[1][0].items() if key not in signatures},
                           tuple(row for row in before[1][1] if row[0] not in TABLES))
        command.downgrade(config, "0106_materials_source_notation")
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert not set(TABLES) & set(inspect(connection).get_table_names(schema="public"))
            assert _snapshot(connection)[0] == legacy
            assert public_objects(connection) == old_objects
        command.upgrade(config, REVISION)
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            assert _snapshot(connection) == before
    return {"empty_roundtrip_preserved_all_rows_and_sql_objects": True, "revision": REVISION}


async def populated_capture(capability):
    """A synthetic actual-code capture, explicitly without any provider RPC."""
    validate_test_environment()
    from sqlalchemy import text

    from models.db import get_engine, get_session_factory
    from services.embedding_receipts import append_embedding_receipt
    from services.retrieval_native import append_input_receipt, append_native_revisions
    from tests.test_embedding_receipts import prepared

    engine = get_engine()
    try:
        with tempfile.TemporaryDirectory(prefix="native-capture-rehearsal-") as folder:
            root = Path(folder)
            async with get_session_factory()() as db:
                connection = await db.connection()
                await connection.run_sync(verify_postgres_identity, capability)
                # Compare every legacy provider-generation record, not counts.
                tables = ("index_generations", "index_generation_members", "index_generation_validations",
                          "index_activation_events", "index_active_pointer")
                async def legacy_rows():
                    return {name: (await db.execute(text(
                        f"SELECT to_jsonb(t)::text FROM public.{name} t ORDER BY to_jsonb(t)::text"))).scalars().all()
                        for name in tables}
                before = await legacy_rows()
                chunk, vector, metadata, _ = await prepared(db)
                complete = await append_embedding_receipt(db, chunk_id=chunk, vector=vector,
                                                          receipt=metadata, dry_run=False)
                source = (await db.execute(text("""SELECT c.paper_id,c.text,e.rendering_version
                    FROM chunks c JOIN chunk_evidence_current link ON link.chunk_id=c.id
                    JOIN rag_evidence_revisions e ON e.id=link.evidence_revision_id WHERE c.id=:id"""),
                    {"id": chunk})).mappings().one()
                payload = json.dumps({"synthetic_renderer_input": source["text"]}).encode()
                path = root / "input.json"
                path.write_bytes(payload)
                receipt = await append_input_receipt(db, archive_root=root, relative_path=path.name,
                    paper_id=source["paper_id"], source_uri="https://example.invalid/synthetic-native-input",
                    source_scope="structured_record", media_type="application/json", parser_version="synthetic-parser/2",
                    chunker_version=source["rendering_version"], expected_bytes=len(payload),
                    provider_sha256=hashlib.sha256(payload).hexdigest(), dry_run=False)
                native = await append_native_revisions(db, input_receipt_id=receipt["input_receipt_id"],
                    items=[{"chunk_id": chunk, "receipt_id": complete["receipt_id"], "vector": vector}], dry_run=False)
                assert await legacy_rows() == before
                assert path.read_bytes() == payload and not native["active_pointer_changed"]
                for table in TABLES:
                    assert await db.scalar(text(f"SELECT bool_and(record_sha256="
                        f"public.sclib_retrieval_record_hash_v2(to_jsonb(t))) FROM public.{table} t")) is True
                await db.commit()
            return {"synthetic": True, "provider_calls_performed": False,
                    "input_sha256": receipt["representation_sha256"],
                    "native_revision_sha256": native["revisions"][0]["record_sha256"],
                    "native_without_provider_generation_created": True,
                    "archive_file_unchanged_during_capture": True}
    finally:
        await engine.dispose()


def retained_history(capability, engine, config):
    from alembic import command
    from services.schema_lifecycle import check_connection_schema

    validate_test_environment()
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before = _snapshot(connection)
        assert all(before[0][name] for name in TABLES)
    try:
        command.downgrade(config, "0106_materials_source_notation")
    except RuntimeError as error:
        assert "retained retrieval input or native revision history" in str(error)
    else:
        raise AssertionError("Native retained history downgrade must fail closed")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        after = _snapshot(connection)
        assert after == before
    return {"nonempty_downgrade_refused": True,
            "all_rows_and_sql_objects_before_sha256": _sha(before),
            "all_rows_and_sql_objects_after_sha256": _sha(after)}
