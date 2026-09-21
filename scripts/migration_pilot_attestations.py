"""0077 checks on guarded newly migrated services; never a shared database."""

from __future__ import annotations

from test_safety import validate_test_environment, verify_postgres_identity

TABLE = "ml_pilot_review_attestations"


def snapshot(connection, *, old_only=False):
    from sqlalchemy import inspect, text

    return {
        name: connection.execute(
            text(
                f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
            )
        )
        .scalars()
        .all()
        for name in inspect(connection).get_table_names(schema="public")
        if not old_only or name not in {TABLE, "scientific_result_passage_links", "alembic_version"}
    }


def objects(connection):
    from sqlalchemy import text

    return (
        connection.execute(
            text(
                "SELECT pg_get_functiondef(to_regprocedure('public.sclib_ml_pilot_attestation_insert_v1()'))"
            )
        ).scalar_one(),
        connection.execute(
            text(
                "SELECT tgname,pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid=to_regclass('public.ml_pilot_review_attestations') AND NOT tgisinternal ORDER BY tgname"
            )
        ).all(),
    )


def empty_roundtrip(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import text

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert (
            connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0
        )
        before, definitions = snapshot(connection, old_only=True), objects(connection)
        assert definitions[0] and len(definitions[1]) == 4
    command.downgrade(config, "0076_ml_pilot_registration")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError:
            pass
        else:
            raise AssertionError("0077 API must refuse 0076 schema")
        verify_postgres_identity(connection, capability)
        assert snapshot(connection, old_only=True) == before
        assert objects(connection) == (None, [])
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection, old_only=True) == before
        assert objects(connection) == definitions


async def populated(capability):
    validate_test_environment()
    from models.db import _to_async_dsn
    from services import ml_pilot_attestations as service
    from services.ml_pilot_documents import canonical
    from services.ml_pilot_review_worker import prepare
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_label_capture import read_snapshot, write_snapshot
    from tests.test_ml_pilot_attestations import payload
    from tests.test_ml_pilot_review_admission import prepared
    from tests.test_research_freeze import state

    engine = create_async_engine(
        _to_async_dsn(capability.database_url),
        isolation_level="SERIALIZABLE",
        poolclass=NullPool,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            await (await db.connection()).run_sync(
                lambda c: verify_postgres_identity(c, capability)
            )
            f, first, _, at = await prepared(db)
            member = first["participants"][0]
            upload = payload(f, member, at)
            checked = prepare(canonical(upload), attestation=True)
            args = {
                **checked["parameters"],
                "actor_user_id": member["user_id"],
                "action": "attest",
                "document_check": checked["document_check"],
                "implementation": checked["implementation"],
            }
            before = await state(db)
            preview = await service.decide(db, **args)
            assert preview["declaration"] is None and await state(db) == before
            args.update(dry_run=False, expected_intent_sha256=preview["intent_sha256"])
            signed = await service.decide(db, **args)
            await db.rollback()
            assert await state(db) == before
            signed = await service.decide(db, **args)
            await db.commit()
            row = signed["declaration"]
            withdraw = {
                key: value
                for key, value in args.items()
                if key not in {"document_check", "implementation"}
            }
            withdraw.update(
                action="withdraw",
                supersedes_id=row["id"],
                supersedes_sha256=row["record_sha256"],
                request_key="synthetic-migration-withdraw",
                dry_run=True,
                expected_intent_sha256=None,
            )
            await write_snapshot(db)
            preview = await service.decide(db, **withdraw)
            withdraw.update(
                dry_run=False, expected_intent_sha256=preview["intent_sha256"]
            )
            removed = await service.decide(db, **withdraw)
            await db.commit()
            after = await state(db)
            assert len(after[TABLE]) == 2
            await read_snapshot(db)
            old = await service.outcome(
                db,
                actor_user_id=member["user_id"],
                request_key=args["request_key"],
                expected_intent_sha256=args["expected_intent_sha256"],
            )
            assert old["declaration"] == row and old["replayed"]
            assert removed["declaration"]["basis"] == row["basis"]
            assert not old["scientific_acceptance"] and await state(db) == after
    finally:
        await engine.dispose()


def retained_history(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import check_connection_schema

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before, definitions = snapshot(connection), objects(connection)
        assert len(before[TABLE]) == 2
    try:
        command.downgrade(config, "0076_ml_pilot_registration")
    except RuntimeError as exc:
        assert "immutable review declaration history exists" in str(exc)
    else:
        raise AssertionError("0077 downgrade must retain scientific declarations")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before and objects(connection) == definitions
