"""Independent 0088 inventory for older owned migration round trips.

Only explicitly empty condition ledgers may be omitted from old-head snapshots.
Importing this inventory opens no clients or connections.
"""

from migration_discovery_feedback import TABLES as FEEDBACK_TABLES
from migration_discovery_feedback import assert_empty as assert_empty_feedback
from migration_discovery_feedback import function_signatures as feedback_function_signatures

TABLES = ("discovery_condition_batches_v1", "discovery_condition_child_links_v1")


def assert_empty(connection):
    from sqlalchemy import text

    for name in TABLES:
        assert connection.execute(text(f'SELECT count(*) FROM public."{name}"')).scalar_one() == 0


def function_signatures():
    from models.discovery_condition_batch_v1 import FUNCTION_SIGNATURES

    return FUNCTION_SIGNATURES


def empty_roundtrip(capability, engine, config):
    """Rehearse only 0088 with actual retained older rows and SQL definitions."""
    from alembic import command
    from sqlalchemy import inspect, text
    from services.schema_lifecycle import SchemaLifecycleError, check_connection_schema
    from migration_source_expressions import public_objects
    from test_safety import validate_test_environment, verify_postgres_identity

    def snapshot(connection):
        connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        return {name: connection.execute(text(
            f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text')).scalars().all()
            for name in inspect(connection).get_table_names(schema="public")
            if name not in {"alembic_version", *TABLES, *FEEDBACK_TABLES}}

    validate_test_environment()
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        assert_empty(connection)
        assert_empty_feedback(connection)
        before, definitions = snapshot(connection), public_objects(connection)
        assert any(before.values()), "Earlier rehearsal rows must actually be retained"
        signatures = {connection.execute(text("SELECT to_regprocedure(:signature)::text"),
            {"signature": f"public.{name}({arguments})"}).scalar_one()
            for name, arguments in (*function_signatures(), *feedback_function_signatures())}
        assert None not in signatures
        triggers = {(row[0], row[1]) for row in definitions[1] if row[0] in TABLES}
        assert triggers == {(name, "cb88_" + suffix) for name in TABLES
                            for suffix in ("insert", "immutable", "truncate")}
        earlier = ({key: value for key, value in definitions[0].items() if key not in signatures},
                   tuple(row for row in definitions[1] if row[0] not in {*TABLES, *FEEDBACK_TABLES}))
    command.downgrade(config, "0087_discovery_designs")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        try:
            check_connection_schema(connection)
        except SchemaLifecycleError as exc:
            assert "exact revision" in str(exc)
        else:
            raise AssertionError("0088 API must refuse actual 0087 schema")
        assert not {*TABLES, *FEEDBACK_TABLES} & set(inspect(connection).get_table_names(schema="public"))
        assert snapshot(connection) == before and public_objects(connection) == earlier
    validate_test_environment()
    command.upgrade(config, "head")
    with engine.connect() as connection:
        verify_postgres_identity(connection, capability)
        connection.rollback()
        assert check_connection_schema(connection)["status"] == "compatible"
        assert_empty(connection)
        assert_empty_feedback(connection)
        assert snapshot(connection) == before and public_objects(connection) == definitions
    print("Empty 0088 round trip preserved every earlier SQL row, function and trigger.")
