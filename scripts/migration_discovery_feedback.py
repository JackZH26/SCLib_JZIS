"""Explicit empty 0089 inventory and actual owned migration round trip."""

from migration_discovery_calculations import TABLES as CALCULATION_TABLES
from migration_discovery_calculations import assert_empty as assert_empty_calculations
from migration_discovery_calculations import function_signatures as calculation_function_signatures

TABLES = ("discovery_evidence_returns_v1", "discovery_feedback_follow_ups_v1")


def assert_empty(connection):
    from sqlalchemy import text

    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0


def function_signatures():
    from models.discovery_feedback_v1 import FUNCTION_SIGNATURES

    return FUNCTION_SIGNATURES


def empty_roundtrip(capability, engine, config):
    from migration_revision_scope import at_revision

    with at_revision(capability, engine, config, "0090_discovery_calculations"):
        _roundtrip_at_0090(capability, engine, config)


def _roundtrip_at_0090(capability, engine, config):
    from alembic import command
    from migration_revision_scope import assert_revision
    from sqlalchemy import inspect, text
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from migration_source_expressions import public_objects
    from test_safety import validate_test_environment, verify_postgres_identity

    def snapshot(connection):
        connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        return {name: connection.execute(text(
            f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text')).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")
            if name not in {"alembic_version", *TABLES, *CALCULATION_TABLES}}

    validate_test_environment()
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert_revision(connection, "0090_discovery_calculations")
        assert_empty(connection)
        assert_empty_calculations(connection)
        before, definitions = snapshot(connection), public_objects(connection)
        assert any(before.values()), "Earlier rehearsal rows must actually be retained"
        signatures = {connection.execute(text("SELECT to_regprocedure(:signature)::text"),
            {"signature": f"public.{name}({arguments})"}).scalar_one()
            for name, arguments in (*function_signatures(), *calculation_function_signatures())}
        assert None not in signatures
        triggers = {(row[0], row[1]) for row in definitions[1] if row[0] in TABLES}
        assert triggers == {(name, "df89_" + suffix) for name in TABLES
                            for suffix in ("insert", "immutable", "truncate")}
        earlier = ({key: value for key, value in definitions[0].items() if key not in signatures},
                   tuple(row for row in definitions[1] if row[0] not in {*TABLES, *CALCULATION_TABLES}))
    command.downgrade(config, "0088_discovery_condition_batches")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("0089 API must refuse actual 0088 schema")
        assert not {*TABLES, *CALCULATION_TABLES} & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before and public_objects(connection) == earlier
    validate_test_environment()
    command.upgrade(config, "0090_discovery_calculations")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert_revision(connection, "0090_discovery_calculations")
        assert_empty(connection)
        assert_empty_calculations(connection)
        assert snapshot(connection) == before and public_objects(connection) == definitions
    print("Empty 0089 round trip preserved every earlier SQL row, function and trigger.")
