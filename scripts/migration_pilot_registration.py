"""0076 integration on the runner's actual migrated, owned synthetic database.

No schema creation from ORM metadata, trigger disabling, source access or human
approval. Importing this helper does not import clients or open connections.
"""

from __future__ import annotations

from test_safety import validate_test_environment, verify_postgres_identity

TABLES = (
    "ml_pilot_registrations",
    "ml_pilot_participants",
    "ml_pilot_participation_decisions",
)


def snapshot(connection, *, old_only=False):
    from sqlalchemy import inspect, text

    connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    return {
        name: connection.execute(
            text(
                f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
            )
        )
        .scalars()
        .all()
        for name in inspect(connection).get_table_names(schema="public")
        if not old_only
        or name not in {"alembic_version", *TABLES, "ml_pilot_review_attestations", "scientific_result_passage_links"}
    }


def objects(connection):
    from models.ml_pilot_registration_v1 import FUNCTIONS
    from sqlalchemy import text

    functions = [
        connection.execute(
            text("SELECT pg_get_functiondef(to_regprocedure(:name))"),
            {"name": "public." + name + "()"},
        ).scalar_one()
        for name in FUNCTIONS
    ]
    triggers = connection.execute(
        text("""SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(:tables) AND NOT t.tgisinternal
        ORDER BY c.relname,t.tgname"""),
        {"tables": list(TABLES)},
    ).all()
    return functions, triggers


def empty_roundtrip(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from sqlalchemy import inspect, text

    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert all(
            connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one()
            == 0
            for name in TABLES
        )
        before, definitions = snapshot(connection, old_only=True), objects(connection)
        assert all(definitions[0]) and len(definitions[1]) == 13
    validate_test_environment()
    command.downgrade(config, "0075_ml_run_evidence")
    with engine.connect() as connection:
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("0076 API must refuse the actual 0075 database")
        verify_postgres_identity(connection, capability)
        assert not set(TABLES) & set(
            inspect(connection).get_table_names(schema="public")
        )
        assert objects(connection) == ([None, None], [])
        assert snapshot(connection, old_only=True) == before
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection, old_only=True) == before
        assert objects(connection) == definitions
        assert all(
            connection.execute(text(f"SELECT count(*) FROM public.{name}")).scalar_one()
            == 0
            for name in TABLES
        )


async def populated_history(capability):
    validate_test_environment()
    from models.db import _to_async_dsn
    from services import ml_pilot_registration as service
    from services.ml_pilot_documents import canonical
    from services.research_audit_retention import has_research_audit_references
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool
    from tests.test_ml_label_capture import read_snapshot, write_snapshot
    from tests.test_ml_pilot_registration import (
        confirmed,
        decision_args,
        fixture,
        no_authority,
        registered,
    )
    from tests.test_research_freeze import state

    engine = create_async_engine(
        _to_async_dsn(capability.database_url),
        isolation_level="SERIALIZABLE",
        poolclass=NullPool,
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await (await session.connection()).run_sync(
                lambda raw: verify_postgres_identity(raw, capability)
            )
            f = await fixture(session)
            await session.commit()
            before = await state(session)
            preview = await service.register(session, **f["args"])
            assert await state(session) == before
            no_authority(preview)

            # Bypass the service's complete-roster loop, not the SQL guard.
            # One valid member is insufficient for the committed three-member roster.
            intent = preview["intent"]
            try:
                async with session.begin_nested():
                    reg = await service.insert(
                        session,
                        TABLES[0],
                        {
                            **{
                                key: value
                                for key, value in intent.items()
                                if key != "version"
                            },
                            "intent_json": canonical(intent).decode(),
                            "intent_sha256": preview["intent_sha256"],
                            "roster_json": canonical(
                                f["args"]["commitment"]["participant_bindings"]
                            ).decode(),
                            "implementation_json": canonical(
                                f["args"]["implementation"]
                            ).decode(),
                        },
                    )
                    member = f["args"]["commitment"]["participant_bindings"][0]
                    await service.insert(
                        session,
                        TABLES[1],
                        {
                            "registration_id": reg["id"],
                            "registration_sha256": reg["record_sha256"],
                            "user_id": member["user_id"],
                            "reviewer_grant_id": member["reviewer_grant_id"],
                            "alias_sha256": member["alias_sha256"],
                            "roles_json": canonical(member["roles"]).decode(),
                        },
                    )
                    await session.execute(
                        text("SET CONSTRAINTS mp76_complete IMMEDIATE")
                    )
            except DBAPIError as exc:
                assert (
                    exc.orig.sqlstate == "23514"
                    and "ml_pilot_complete_distinct_roster_required" in str(exc.orig)
                )
            else:
                raise AssertionError(
                    "Partial pilot roster must fail on the actual migrated schema"
                )
            assert await state(session) == before

            # Service commit means only its nested transaction; the caller owns durability.
            await registered(session, f["args"])
            await session.rollback()
            assert await state(session) == before
            first = await registered(session, f["args"])
            no_authority(first)
            await session.commit()
            after_registration = await state(session)
            replay = await service.register(
                session,
                **f["args"],
                dry_run=False,
                expected_intent_sha256=first["intent_sha256"],
            )
            assert (
                replay["replayed"] and replay["registration"] == first["registration"]
            )
            assert await state(session) == after_registration
            accepts = []
            for member in first["participants"]:
                accepted = await confirmed(session, decision_args(member, f["inputs"]))
                no_authority(accepted)
                accepts.append(accepted["decision"])
            await session.commit()

        # A new physical connection observes real commits, not in-session fixtures.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await (await session.connection()).run_sync(
                lambda raw: verify_postgres_identity(raw, capability)
            )
            await session.rollback()
            await read_snapshot(session)
            ref = {
                "registration_id": first["registration"]["id"],
                "registration_sha256": first["registration"]["record_sha256"],
            }
            result = await service.inspect(session, actor_user_id=f["people"][0], **ref)
            assert (
                result["ready_for_prospective_review"]
                and result["accepted_account_count"] == 3
            )
            no_authority(result)
            for uid in f["people"]:
                assert await has_research_audit_references(session, uid)
            await write_snapshot(session)
            member = first["participants"][0]
            withdrawn = await confirmed(
                session,
                decision_args(
                    member, f["inputs"], decision="withdraw", prior=accepts[0]
                ),
            )
            no_authority(withdrawn)
            await session.commit()
            after_withdrawal = await state(session)
            await read_snapshot(session)
            result = await service.inspect(session, actor_user_id=f["people"][0], **ref)
            assert (
                not result["ready_for_prospective_review"]
                and result["accepted_account_count"] == 2
            )
            no_authority(result)
            recovered = await service.outcome(
                session,
                actor_user_id=member["user_id"],
                kind="participation",
                request_key=accepts[0]["request_key"],
                expected_intent_sha256=accepts[0]["intent_sha256"],
            )
            assert recovered["replayed"] and recovered["decision"] == accepts[0]
            assert await state(session) == after_withdrawal
            assert [len(after_withdrawal[name]) for name in TABLES] == [1, 3, 4]
    finally:
        await engine.dispose()


def populated_roundtrip(capability, engine, config):
    validate_test_environment()
    from alembic import command
    from services.schema_lifecycle import check_connection_schema

    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        before, definitions = snapshot(connection), objects(connection)
        assert [len(before[name]) for name in TABLES] == [1, 3, 4]
    validate_test_environment()
    try:
        command.downgrade(config, "0075_ml_run_evidence")
    except RuntimeError as exc:
        assert "immutable registration or participant history exists" in str(exc)
    else:
        raise AssertionError(
            "0076 downgrade must retain every pilot commitment and decision"
        )
    with engine.connect() as connection:
        assert check_connection_schema(connection)["status"] == "compatible"
        verify_postgres_identity(connection, capability)
        assert snapshot(connection) == before and objects(connection) == definitions
