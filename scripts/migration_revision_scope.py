"""Rehearse an older exact schema without treating it as the application head."""
from contextlib import contextmanager


def assert_revision(connection, revision):
    from alembic.migration import MigrationContext

    assert set(MigrationContext.configure(connection).get_current_heads()) == {revision}


@contextmanager
def at_revision(capability, engine, config, revision):
    from alembic import command
    from migration_source_expressions import public_objects
    from services.schema_lifecycle import check_connection_schema
    from sqlalchemy import inspect, text
    from test_safety import validate_test_environment, verify_postgres_identity

    def complete_snapshot():
        validate_test_environment()
        with engine.connect() as connection:
            verify_postgres_identity(connection, capability)
            connection.rollback()
            assert check_connection_schema(connection)["status"] == "compatible"
            connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
            rows = {name: connection.execute(text(
                f'SELECT to_jsonb(t) FROM public."{name}" t ORDER BY to_jsonb(t)::text'
            )).scalars().all() for name in inspect(connection).get_table_names(schema="public")
                if name != "alembic_version"}
            return rows, public_objects(connection)

    before = complete_snapshot()
    # Later migrations enforce their own retained-history refusal. No ledger is
    # emptied and no function/trigger is excluded from the outer comparison.
    command.downgrade(config, revision)
    try:
        yield
    finally:
        validate_test_environment()
        command.upgrade(config, "head")
        assert complete_snapshot() == before
